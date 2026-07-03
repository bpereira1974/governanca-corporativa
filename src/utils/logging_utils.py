# src/utils/logging_utils.py
import json
import traceback

PROJECT = None  # set at startup from config or env var


def custom_log(msg, component, severity="DEFAULT"):
    """
    Structured logger for GCP Cloud Logging.

    severity options: DEFAULT, DEBUG, INFO, NOTICE, WARNING, ERROR, CRITICAL, ALERT, EMERGENCY
    component: use the route or function path, e.g. "/scoring/calcular_nota"
    """
    global_log_fields = {}

    request_is_defined = "request" in globals() or "request" in locals()
    if request_is_defined and request:
        trace_header = request.headers.get("X-Cloud-Trace-Context")
        if trace_header and PROJECT:
            trace = trace_header.split("/")
            global_log_fields["logging.googleapis.com/trace"] = (
                f"projects/{PROJECT}/traces/{trace[0]}"
            )

    entry = dict(
        severity=severity,
        message=msg,
        component=component,
        **global_log_fields,
    )
    print(json.dumps(entry))
