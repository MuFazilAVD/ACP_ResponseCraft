"""Local prompt resolution and optional Langfuse PromptHub sync."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .langfuse_integration import (
    build_langfuse_client,
    langfuse_auth_check,
    langfuse_config,
)
from .schemas import PromptSyncResponse


@dataclass(frozen=True)
class PromptResolution:
    text: str
    source: str
    prompt_name: str
    prompt_version: int | None
    prompt_label: str
    prompt_variant: str


class PromptManager:
    def __init__(
        self,
        prompt_dir: Path,
        prompt_name: str,
        prompt_label: str,
        langfuse_client: Any | None = None,
    ) -> None:
        self.prompt_dir = prompt_dir
        self.prompt_name = prompt_name
        self.prompt_label = prompt_label
        self._langfuse = langfuse_client if langfuse_client is not None else build_langfuse_client()

    def variants(self) -> dict[str, str]:
        found: dict[str, str] = {}
        if not self.prompt_dir.exists():
            return found
        for path in sorted(self.prompt_dir.glob("*.md")):
            text = path.read_text(encoding="utf-8").strip()
            if not text:
                continue
            variant = "default" if path.stem == "default" else path.stem.lower()
            found[variant] = text
        return found

    def prompt_name_map(self) -> dict[str, str]:
        variants = self.variants()
        if not variants:
            return {"default": self.prompt_name}
        return {
            variant: self._name_for_variant(variant)
            for variant in sorted(variants, key=lambda v: (v != "default", v))
        }

    def resolve(self, model_name: str, system_prompt_override: str | None = None) -> PromptResolution:
        variants = self.variants()
        selected = self._select_variant(model_name, set(variants))
        local_text = variants.get(selected) or variants.get("default") or ""
        prompt_name = self._name_for_variant(selected)

        if system_prompt_override:
            return PromptResolution(
                text=system_prompt_override,
                source="override",
                prompt_name=prompt_name,
                prompt_version=None,
                prompt_label=self.prompt_label,
                prompt_variant=selected,
            )

        remote = self._load_langfuse_prompt(prompt_name, selected)
        if remote:
            return remote

        return PromptResolution(
            text=local_text,
            source="local",
            prompt_name=prompt_name,
            prompt_version=None,
            prompt_label=self.prompt_label,
            prompt_variant=selected,
        )

    def sync(self) -> PromptSyncResponse:
        variants = self.variants()
        if not variants:
            return PromptSyncResponse(
                status="error",
                prompt_name=self.prompt_name,
                prompt_label=self.prompt_label,
                source="local",
                message="No local prompt files found under prompts/*.md.",
            )

        if self._langfuse is None:
            return PromptSyncResponse(
                status="skipped",
                prompt_name=self.prompt_name,
                prompt_label=self.prompt_label,
                source="local",
                message="Langfuse credentials/client unavailable; local prompts are ready to sync.",
                variants=self.prompt_name_map(),
            )

        if langfuse_config().auth_check_on_sync:
            authenticated, message = langfuse_auth_check(self._langfuse)
            if authenticated is False:
                return PromptSyncResponse(
                    status="error",
                    prompt_name=self.prompt_name,
                    prompt_label=self.prompt_label,
                    source="langfuse",
                    message=message,
                    variants=self.prompt_name_map(),
                )

        created = 0
        updated = 0
        unchanged = 0
        version: int | None = None
        for variant, prompt_text in variants.items():
            name = self._name_for_variant(variant)
            existing = self._load_langfuse_prompt(name, variant)
            if existing and existing.text.strip() == prompt_text.strip():
                unchanged += 1
                version = existing.prompt_version if variant == "default" else version
                continue
            try:
                prompt = self._langfuse.create_prompt(
                    name=name,
                    prompt=prompt_text,
                    labels=[self.prompt_label],
                    tags=["agent:tcs-rfp-response-drafter", f"variant:{variant}", "aei"],
                    type="text",
                    commit_message=f"Sync {name} from local prompts/{variant}.md",
                )
                self._langfuse.flush()
                prompt_version = getattr(prompt, "version", None)
                if isinstance(prompt_version, int) and variant == "default":
                    version = prompt_version
                if existing:
                    updated += 1
                else:
                    created += 1
            except Exception as exc:
                return PromptSyncResponse(
                    status="error",
                    prompt_name=self.prompt_name,
                    prompt_label=self.prompt_label,
                    source="langfuse",
                    message=f"Langfuse sync failed for {name}: {exc.__class__.__name__}",
                    variants=self.prompt_name_map(),
                )

        status = "updated" if updated else "created" if created else "unchanged"
        return PromptSyncResponse(
            status=status,
            prompt_name=self.prompt_name,
            prompt_version=version,
            prompt_label=self.prompt_label,
            source="langfuse",
            message=f"Variants synced: created={created}, updated={updated}, unchanged={unchanged}.",
            variants=self.prompt_name_map(),
        )

    def _select_variant(self, model_name: str, available: set[str]) -> str:
        if not available:
            return "default"
        model = model_name.lower()
        for variant, tokens in {
            "claude": ("claude", "anthropic"),
            "gpt": ("gpt", "openai"),
            "gemini": ("gemini", "vertex", "google"),
        }.items():
            if variant in available and any(token in model for token in tokens):
                return variant
        return "default" if "default" in available else sorted(available)[0]

    def _name_for_variant(self, variant: str) -> str:
        return self.prompt_name if variant == "default" else f"{self.prompt_name}--{variant}"

    def _load_langfuse_prompt(self, prompt_name: str, variant: str) -> PromptResolution | None:
        if self._langfuse is None:
            return None
        try:
            prompt = self._langfuse.get_prompt(
                name=prompt_name,
                label=self.prompt_label,
                type="text",
            )
            text = getattr(prompt, "prompt", None) or getattr(prompt, "content", None)
            version = getattr(prompt, "version", None)
            if not isinstance(text, str) or not text.strip():
                return None
            return PromptResolution(
                text=text.strip(),
                source="langfuse",
                prompt_name=prompt_name,
                prompt_version=version if isinstance(version, int) else None,
                prompt_label=self.prompt_label,
                prompt_variant=variant,
            )
        except Exception:
            return None
