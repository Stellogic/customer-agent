param(
    [Parameter(Mandatory)]
    [AllowEmptyCollection()]
    [string[]]$LogLines
)

$counts = [ordered]@{}
foreach ($phase in @('START', 'FOLLOWUP')) {
    $counts[$phase] = [ordered]@{
        TRANSPORT = 0
        RESPONSE_PARSE = 0
        STATE_CONSISTENCY = 0
        SERVICE_VALIDATION = 0
    }
}
foreach ($line in $LogLines) {
    if ($line -match '\bINTAKE_FAILURE phase=(START|FOLLOWUP) reason=(TRANSPORT|RESPONSE_PARSE|STATE_CONSISTENCY|SERVICE_VALIDATION)(?:\s|$)') {
        $counts[$Matches[1]][$Matches[2]]++
    }
}
# 仅返回固定枚举计数，不输出原始日志；全零不代表受理成功。
[pscustomobject]$counts
