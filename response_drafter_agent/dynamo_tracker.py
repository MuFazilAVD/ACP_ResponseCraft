"""DynamoDB invocation tracker for the TCS RFP Response Drafter agent.

This module provides a single ``InvokeTracker`` class that creates and
progressively updates a DynamoDB item for each ``/invoke`` request.

Item lifecycle
--------------
1. ``start()``       – PutItem with status="started"
2. ``record_tool()`` – UpdateItem after the MCP tool returns
3. ``record_no_tool()`` – UpdateItem marking tool_call=False (retrieval skipped)
4. ``fail()``        – UpdateItem with status="failed" + error details
5. ``complete()``    – UpdateItem with final_answer + status="completed"

All DynamoDB I/O errors are caught and logged so that a tracker failure
**never** blocks or alters the agent's normal response path.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from .logging_utils import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Table configuration (resolved once at import time)
# ---------------------------------------------------------------------------

TABLE_NAME = "ACP_RC_ResponseDrafter"

_dynamodb_region: str = os.getenv("DYNAMODB_REGION", "ap-south-1")
_aws_access_key_id: str | None = os.getenv("AWS_ACCESS_KEY_ID")
_aws_secret_access_key: str | None = os.getenv("AWS_SECRET_ACCESS_KEY")


def _build_table() -> Any:
    """Build and return the DynamoDB Table resource.

    Returns ``None`` if credentials or region are missing so that the rest of
    the module can degrade gracefully.
    """
    if not _aws_access_key_id or not _aws_secret_access_key:
        logger.warning(
            "[dynamo_tracker] AWS credentials not configured — DynamoDB tracking disabled "
            "| AWS_ACCESS_KEY_ID_set=%s | AWS_SECRET_ACCESS_KEY_set=%s",
            bool(_aws_access_key_id),
            bool(_aws_secret_access_key),
        )
        return None

    try:
        dynamodb_resource = boto3.resource(
            "dynamodb",
            region_name=_dynamodb_region,
            aws_access_key_id=_aws_access_key_id,
            aws_secret_access_key=_aws_secret_access_key,
        )
        table = dynamodb_resource.Table(TABLE_NAME)
        logger.info(
            "[dynamo_tracker] DynamoDB table resource created | table=%s | region=%s",
            TABLE_NAME,
            _dynamodb_region,
        )
        return table
    except (BotoCoreError, ClientError, Exception) as exc:
        logger.error(
            "[dynamo_tracker] Failed to create DynamoDB table resource | error=%s | detail=%s",
            exc.__class__.__name__,
            str(exc),
            exc_info=True,
        )
        return None


# Module-level table handle (shared across all requests)
_table = _build_table()


# ---------------------------------------------------------------------------
# Tracker class
# ---------------------------------------------------------------------------


class InvokeTracker:
    """Tracks a single ``/invoke`` execution in DynamoDB.

    Parameters
    ----------
    invoke_id:
        UUID primary key for this invocation (caller-generated).
    input_query:
        The raw query string from the incoming request.
    """

    def __init__(self, invoke_id: str, input_query: str) -> None:
        self.invoke_id = invoke_id
        self.input_query = input_query
        self._start_time = time.perf_counter()

    # ------------------------------------------------------------------
    # Public lifecycle methods
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Create the initial DynamoDB item with status='started'."""
        if _table is None:
            return

        item: dict[str, Any] = {
            "invoke_id": self.invoke_id,
            "input_query": self.input_query,
            "status": "started",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        logger.info(
            "[InvokeTracker.start] Creating DynamoDB item | invoke_id=%s | status=started",
            self.invoke_id,
        )
        logger.debug("[InvokeTracker.start] Item payload | %s", item)

        try:
            _table.put_item(Item=item)
            logger.info(
                "[InvokeTracker.start] DynamoDB item created successfully | invoke_id=%s",
                self.invoke_id,
            )
        except (BotoCoreError, ClientError, Exception) as exc:
            logger.error(
                "[InvokeTracker.start] Failed to create DynamoDB item | invoke_id=%s | "
                "error=%s | detail=%s",
                self.invoke_id,
                exc.__class__.__name__,
                str(exc),
                exc_info=True,
            )

    def record_tool(
        self,
        *,
        tool_arguments: dict[str, Any],
        retrieved_chunks: Any,
        mcp_tool_latency: float,
    ) -> None:
        """Update the DynamoDB item with MCP tool call details.

        Parameters
        ----------
        tool_arguments:
            The arguments that were passed to the MCP tool.
        retrieved_chunks:
            The response payload returned by the MCP tool (serialisable object).
        mcp_tool_latency:
            End-to-end latency (in seconds) for the MCP tool call.
        """
        if _table is None:
            return

        logger.info(
            "[InvokeTracker.record_tool] Updating DynamoDB item with tool call details | "
            "invoke_id=%s | mcp_tool_latency=%.3fs",
            self.invoke_id,
            mcp_tool_latency,
        )
        logger.debug(
            "[InvokeTracker.record_tool] tool_arguments=%s | retrieved_chunks (preview)=%s",
            tool_arguments,
            str(retrieved_chunks)[:300] if retrieved_chunks else "",
        )

        try:
            # Serialise retrieved_chunks to a plain string if needed so DynamoDB
            # can store it without type errors on complex nested objects.
            if isinstance(retrieved_chunks, (dict, list)):
                chunks_value: str = json.dumps(retrieved_chunks, ensure_ascii=False, default=str)
            elif retrieved_chunks is None:
                chunks_value = ""
            else:
                chunks_value = str(retrieved_chunks)

            _table.update_item(
                Key={"invoke_id": self.invoke_id},
                UpdateExpression=(
                    "SET tool_call = :tc, "
                    "tool_arguments = :ta, "
                    # "tool_arguments_latency = :tal, "
                    "retrieved_chunks = :rc, "
                    "mcp_tool_latency = :mtl"
                ),
                ExpressionAttributeValues={
                    ":tc": True,
                    ":ta": tool_arguments,
                    # ":tal": str(round(tool_arguments_latency, 4)),
                    ":rc": chunks_value,
                    ":mtl": str(round(mcp_tool_latency, 4)),
                },
            )
            logger.info(
                "[InvokeTracker.record_tool] DynamoDB item updated with tool call details | "
                "invoke_id=%s",
                self.invoke_id,
            )
        except (BotoCoreError, ClientError, Exception) as exc:
            logger.error(
                "[InvokeTracker.record_tool] Failed to update DynamoDB item | invoke_id=%s | "
                "error=%s | detail=%s",
                self.invoke_id,
                exc.__class__.__name__,
                str(exc),
                exc_info=True,
            )

    def record_no_tool(self) -> None:
        """Mark that no tool was called during this invocation."""
        if _table is None:
            return

        logger.info(
            "[InvokeTracker.record_no_tool] Marking tool_call=False | invoke_id=%s",
            self.invoke_id,
        )
        try:
            _table.update_item(
                Key={"invoke_id": self.invoke_id},
                UpdateExpression="SET tool_call = :tc",
                ExpressionAttributeValues={":tc": False},
            )
            logger.info(
                "[InvokeTracker.record_no_tool] DynamoDB item updated | invoke_id=%s",
                self.invoke_id,
            )
        except (BotoCoreError, ClientError, Exception) as exc:
            logger.error(
                "[InvokeTracker.record_no_tool] Failed to update DynamoDB item | invoke_id=%s | "
                "error=%s | detail=%s",
                self.invoke_id,
                exc.__class__.__name__,
                str(exc),
                exc_info=True,
            )

    def fail(self, *, error_message: str, error_type: str) -> None:
        """Update the DynamoDB item to reflect a failed invocation.

        Parameters
        ----------
        error_message:
            Human-readable description of the error.
        error_type:
            The exception class name (e.g. ``ValueError``).
        """
        if _table is None:
            return

        logger.info(
            "[InvokeTracker.fail] Marking invocation as failed | invoke_id=%s | "
            "error_type=%s | error_message=%s",
            self.invoke_id,
            error_type,
            error_message,
        )
        try:
            _table.update_item(
                Key={"invoke_id": self.invoke_id},
                UpdateExpression=(
                    "SET #st = :s, error_message = :em, error_type = :et, "
                    "failed_at = :fa"
                ),
                ExpressionAttributeNames={"#st": "status"},
                ExpressionAttributeValues={
                    ":s": "failed",
                    ":em": error_message,
                    ":et": error_type,
                    ":fa": datetime.now(timezone.utc).isoformat(),
                },
            )
            logger.info(
                "[InvokeTracker.fail] DynamoDB item updated with failure details | invoke_id=%s",
                self.invoke_id,
            )
        except (BotoCoreError, ClientError, Exception) as exc:
            logger.error(
                "[InvokeTracker.fail] Failed to update DynamoDB item | invoke_id=%s | "
                "error=%s | detail=%s",
                self.invoke_id,
                exc.__class__.__name__,
                str(exc),
                exc_info=True,
            )

    def complete(self, *, final_answer: str, final_answer_latency: float) -> None:
        """Update the DynamoDB item with the final answer and mark as completed.

        Parameters
        ----------
        final_answer:
            The response text returned by the agent.
        final_answer_latency:
            Total elapsed time in seconds from invocation start to answer ready.
        """
        if _table is None:
            return

        completed_at = datetime.now(timezone.utc).isoformat()
        logger.info(
            "[InvokeTracker.complete] Marking invocation as completed | invoke_id=%s | "
            "final_answer_latency=%.3fs | completed_at=%s",
            self.invoke_id,
            final_answer_latency,
            completed_at,
        )
        logger.debug(
            "[InvokeTracker.complete] final_answer preview | invoke_id=%s | preview=%s",
            self.invoke_id,
            final_answer[:200] if final_answer else "",
        )

        try:
            _table.update_item(
                Key={"invoke_id": self.invoke_id},
                UpdateExpression=(
                    "SET #st = :s, final_answer = :fa, "
                    "final_answer_latency = :fal, completed_at = :cat"
                ),
                ExpressionAttributeNames={"#st": "status"},
                ExpressionAttributeValues={
                    ":s": "completed",
                    ":fa": final_answer,
                    ":fal": str(round(final_answer_latency, 4)),
                    ":cat": completed_at,
                },
            )
            logger.info(
                "[InvokeTracker.complete] DynamoDB item updated as completed | invoke_id=%s",
                self.invoke_id,
            )
        except (BotoCoreError, ClientError, Exception) as exc:
            logger.error(
                "[InvokeTracker.complete] Failed to update DynamoDB item | invoke_id=%s | "
                "error=%s | detail=%s",
                self.invoke_id,
                exc.__class__.__name__,
                str(exc),
                exc_info=True,
            )
