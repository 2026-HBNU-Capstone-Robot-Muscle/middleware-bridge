const url = process.argv[2] ?? 'ws://127.0.0.1:9090';
const ws = new WebSocket(url);
let serviceResponse;
let topicRoundTrip;
let receivedTalkerMessage;
let finished = false;

const timeout = setTimeout(() => fail(`검증 시간 초과: ${url}`), 10000);

function finish() {
  if (finished || !serviceResponse || !topicRoundTrip || !receivedTalkerMessage) return;
  finished = true;
  clearTimeout(timeout);
  console.log('PASS rosbridge WebSocket 연결');
  console.log('PASS /chatter talker 메시지 수신');
  console.log('PASS /chatter 메시지 발행 및 왕복 수신');
  console.log(`PASS /add_two_ints 서비스 응답: ${JSON.stringify(serviceResponse.values)}`);
  ws.close(1000, '검증 완료');
}

function fail(message) {
  if (finished) return;
  finished = true;
  clearTimeout(timeout);
  console.error(`FAIL ${message}`);
  ws.close();
  process.exitCode = 1;
}

ws.addEventListener('open', () => {
  console.log(`연결됨: ${url}`);
  ws.send(JSON.stringify({
    op: 'subscribe',
    topic: '/chatter',
    type: 'std_msgs/msg/String',
    throttle_rate: 0,
    queue_length: 1,
  }));
});

ws.addEventListener('message', ({ data }) => {
  let message;
  try {
    message = JSON.parse(data);
  } catch {
    return;
  }

  if (message.op === 'status' && /error/i.test(message.level ?? '')) {
    fail(`rosbridge 오류: ${message.msg}`);
    return;
  }

  if (message.op === 'publish' && message.topic === '/chatter') {
    if (!receivedTalkerMessage && /^Hello World:/.test(message.msg?.data ?? '')) {
      receivedTalkerMessage = true;
      ws.send(JSON.stringify({
        op: 'publish',
        topic: '/chatter',
        type: 'std_msgs/msg/String',
        msg: { data: 'rosbridge round-trip check' },
      }));
    }
    if (message.msg?.data === 'rosbridge round-trip check') topicRoundTrip = true;
    finish();
    return;
  }

  if (message.op === 'service_response' && message.id === 'add-two-ints-check') {
    if (!message.result || message.values?.sum !== 42) {
      fail(`예상한 합계 42를 받지 못했습니다: ${JSON.stringify(message)}`);
      return;
    }
    serviceResponse = message;
    finish();
  }
});

ws.addEventListener('error', () => fail(`WebSocket 연결 오류: ${url}`));

ws.addEventListener('open', () => {
  setTimeout(() => {
    if (ws.readyState !== WebSocket.OPEN || finished) return;
    ws.send(JSON.stringify({
      op: 'call_service',
      id: 'add-two-ints-check',
      service: '/add_two_ints',
      type: 'example_interfaces/srv/AddTwoInts',
      args: { a: 17, b: 25 },
    }));
  }, 100);
});
