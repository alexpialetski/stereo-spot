"""
AWS operator-facing console links: CloudWatch Logs Insights and Cost Explorer.

Implements OperatorLinksProvider from shared-types. Used by the web-ui when
running on AWS to show "Open logs" and "Cost" links without embedding AWS URLs
in the app package.
"""

# CloudWatch Logs Insights: INFO/WARNING/ERROR only, job_id filter, ECS + SageMaker log groups.
# Query: level filter to exclude DEBUG (e.g. SSE events); job_id to scope to one job.
# Placeholders: *3cJOB_ID*3e (encoded <JOB_ID> in query), {name_prefix}, {region}.
_CLOUDWATCH_LOGS_INSIGHTS_TEMPLATE = (
    "https://{region}.console.aws.amazon.com/cloudwatch/home?region={region}"
    "#logsV2:logs-insights$3FqueryDetail$3D~(end~0~start~-3600~timeType~'RELATIVE~tz~'UTC~unit~'seconds"
    "~editorString~'fields*20*40timestamp*2c*20*40message*0a*7c*20filter*20*40message*20like*20*2f*5c*5b*28INFO*7cWARNING*7cERROR*29*5c*5d*2f*20and*20*40message*20like*20*2fjob_id*3d*3cJOB_ID*3e*2f*0a*7c*20sort*20*40timestamp*20asc"
    "~queryId~'3680fbd4-54f9-473b-a087-ba0443c8c5b4~source~(~'*2fecs*2f{name_prefix}*2fweb-ui~'*2fecs*2f{name_prefix}*2fvideo-worker~'*2fecs*2f{name_prefix}*2fmedia-worker~'*2faws*2fsagemaker*2fEndpoints*2f{name_prefix}-inference)"
    "~lang~'CWLI~logClass~'STANDARD~queryBy~'logGroupName)"
)

# Cost Explorer: App tag filter, month-to-date, daily granularity. Placeholder: {app_tag_value}.
_DEFAULT_COST_EXPLORER_TEMPLATE = (
    "https://us-east-1.console.aws.amazon.com/costmanagement/home?region=us-east-1"
    "#/cost-explorer?chartStyle=STACK&costAggregate=unBlendedCost&excludeForecasting=false"
    "&filter=%5B%7B%22dimension%22:%7B%22id%22:%22TagKey%22,%22displayValue%22:%22Tag%22%7D,"
    "%22operator%22:%22INCLUDES%22,%22values%22:%5B%7B%22value%22:%22{app_tag_value}%22,"
    "%22displayValue%22:%22{app_tag_value}%22%7D%5D,%22growableValue%22:%7B%22value%22:%22App%22,"
    "%22displayValue%22:%22App%22%7D%7D%5D&futureRelativeRange=CUSTOM&granularity=Daily"
    "&groupBy=%5B%22Service%22%5D&historicalRelativeRange=MONTH_TO_DATE&isDefault=true"
    "&reportMode=STANDARD&reportName=New%20cost%20and%20usage%20report"
    "&showOnlyUncategorized=false&showOnlyUntagged=false&usageAggregate=undefined&useNormalizedUnits=false"
)


class AWSOperatorLinksProvider:
    """AWS implementation of OperatorLinksProvider (CloudWatch Logs Insights + Cost Explorer)."""

    def __init__(
        self,
        name_prefix: str,
        region: str,
        *,
        cost_explorer_url: str | None = None,
    ) -> None:
        self._name_prefix = name_prefix
        self._region = region
        self._cost_explorer_url = cost_explorer_url

    def get_job_logs_url(self, job_id: str) -> str | None:
        """Return CloudWatch Logs Insights URL for this job (log groups + query)."""
        url = _CLOUDWATCH_LOGS_INSIGHTS_TEMPLATE.replace("*3cJOB_ID*3e", job_id)
        return url.format(name_prefix=self._name_prefix, region=self._region)

    def get_cost_dashboard_url(self) -> str | None:
        """Cost Explorer deep link (App tag, month-to-date, daily); or override if set."""
        if self._cost_explorer_url is not None:
            return self._cost_explorer_url
        return _DEFAULT_COST_EXPLORER_TEMPLATE.format(app_tag_value=self._name_prefix)
