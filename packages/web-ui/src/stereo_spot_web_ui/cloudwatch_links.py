"""Build CloudWatch Logs Insights deep-link URL for job logs (template + string replace, no deps)."""

# Template: Logs Insights with job_id filter and ECS + SageMaker log groups.
# Placeholders: *3cJOB_ID*3e (encoded <JOB_ID>), stereo-spot (name prefix), us-east-1 (region).
CLOUDWATCH_LOGS_INSIGHTS_TEMPLATE = (
    "https://us-east-1.console.aws.amazon.com/cloudwatch/home?region=us-east-1"
    "#logsV2:logs-insights$3FqueryDetail$3D~(end~0~start~-3600~timeType~'RELATIVE~tz~'UTC~unit~'seconds"
    "~editorString~'fields*20*40timestamp*2c*20*40logStream*2c*20*40message*0a*7c*20filter*20*40message*20like*20*2fjob_id*3d*3cJOB_ID*3e*2f*0a*7c*20sort*20*40timestamp*20asc"
    "~queryId~'3680fbd4-54f9-473b-a087-ba0443c8c5b4~source~(~'*2fecs*2fstereo-spot*2fweb-ui~'*2fecs*2fstereo-spot*2fvideo-worker~'*2fecs*2fstereo-spot*2fmedia-worker~'*2faws*2fsagemaker*2fEndpoints*2fstereo-spot-inference)"
    "~lang~'CWLI~logClass~'STANDARD~queryBy~'logGroupName)"
)


def build_cloudwatch_logs_insights_url(
    job_id: str,
    name_prefix: str,
    region: str,
) -> str:
    """Return CloudWatch Logs Insights URL with preselected log groups and query for this job."""
    url = CLOUDWATCH_LOGS_INSIGHTS_TEMPLATE.replace("*3cJOB_ID*3e", job_id)
    url = url.replace("stereo-spot", name_prefix)
    url = url.replace("us-east-1", region)
    return url
