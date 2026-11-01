param(
    [string]$Url = 'ws://127.0.0.1:9090'
)

$ErrorActionPreference = 'Stop'
$client = [System.Net.WebSockets.ClientWebSocket]::new()
$cancellation = [System.Threading.CancellationTokenSource]::new([TimeSpan]::FromSeconds(20))
$talkerMessageReceived = $false
$roundTripReceived = $false
$serviceResponse = $null
$roundTripText = 'rosbridge round-trip check'

function Send-RosbridgeMessage {
    param([hashtable]$Message)

    $json = ConvertTo-Json -InputObject $Message -Depth 20 -Compress
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($json)
    $segment = [System.ArraySegment[byte]]::new($bytes)
    [void]$client.SendAsync(
        $segment,
        [System.Net.WebSockets.WebSocketMessageType]::Text,
        $true,
        $cancellation.Token
    ).GetAwaiter().GetResult()
}

function Receive-RosbridgeMessage {
    $buffer = [byte[]]::new(8192)
    $stream = [System.IO.MemoryStream]::new()
    do {
        $segment = [System.ArraySegment[byte]]::new($buffer)
        $result = $client.ReceiveAsync($segment, $cancellation.Token).GetAwaiter().GetResult()
        if ($result.MessageType -eq [System.Net.WebSockets.WebSocketMessageType]::Close) {
            throw 'rosbridge가 WebSocket 연결을 닫았습니다.'
        }
        $stream.Write($buffer, 0, $result.Count)
    } while (-not $result.EndOfMessage)

    $json = [System.Text.Encoding]::UTF8.GetString($stream.ToArray())
    $stream.Dispose()
    return ConvertFrom-Json -InputObject $json
}

try {
    [void]$client.ConnectAsync([Uri]$Url, $cancellation.Token).GetAwaiter().GetResult()
    Write-Output "연결됨: $Url"

    Send-RosbridgeMessage @{
        op = 'subscribe'
        topic = '/chatter'
        type = 'std_msgs/msg/String'
        throttle_rate = 0
        queue_length = 1
    }
    Send-RosbridgeMessage @{
        op = 'call_service'
        id = 'add-two-ints-check'
        service = '/add_two_ints'
        type = 'example_interfaces/srv/AddTwoInts'
        args = @{ a = 17; b = 25 }
    }

    while (-not ($talkerMessageReceived -and $roundTripReceived -and $serviceResponse)) {
        $message = Receive-RosbridgeMessage

        if ($message.op -eq 'status' -and $message.level -eq 'error') {
            throw "rosbridge 오류: $($message.msg)"
        }

        if ($message.op -eq 'publish' -and $message.topic -eq '/chatter') {
            $data = [string]$message.msg.data
            if (-not $talkerMessageReceived -and $data.StartsWith('Hello World:')) {
                $talkerMessageReceived = $true
                Send-RosbridgeMessage @{
                    op = 'publish'
                    topic = '/chatter'
                    type = 'std_msgs/msg/String'
                    msg = @{ data = $roundTripText }
                }
            }
            if ($data -eq $roundTripText) {
                $roundTripReceived = $true
            }
        }

        if ($message.op -eq 'service_response' -and $message.id -eq 'add-two-ints-check') {
            if (-not $message.result -or [int]$message.values.sum -ne 42) {
                throw "예상 합계 42를 받지 못했습니다: $(ConvertTo-Json $message -Compress -Depth 10)"
            }
            $serviceResponse = $message
        }
    }

    Write-Output 'PASS rosbridge WebSocket 연결'
    Write-Output 'PASS /chatter talker 메시지 수신'
    Write-Output 'PASS /chatter 발행 메시지 왕복 수신'
    Write-Output "PASS /add_two_ints 서비스 응답: $(ConvertTo-Json $serviceResponse.values -Compress)"
}
catch {
    Write-Error "FAIL $($_.Exception.Message)"
    exit 1
}
finally {
    $cancellation.Cancel()
    if ($client.State -eq [System.Net.WebSockets.WebSocketState]::Open) {
        [void]$client.CloseAsync(
            [System.Net.WebSockets.WebSocketCloseStatus]::NormalClosure,
            '검증 완료',
            [System.Threading.CancellationToken]::None
        ).GetAwaiter().GetResult()
    }
    $client.Dispose()
    $cancellation.Dispose()
}
