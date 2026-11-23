const ROS = {
  solutionTopic: '/cube/solution',
  solutionType: 'system_interfaces/msg/CubeSolution',
  executionTopic: '/cube/execution_status',
  executionType: 'system_interfaces/msg/CubeExecutionStatus',
  cameraStateTopic: '/cube/camera_active',
  cameraStateType: 'std_msgs/msg/Bool',
  cameraListService: '/cube/list_cameras',
  cameraService: '/cube/set_camera_enabled',
  hardwareReadyTopic: '/cube/real_mode_ready',
  hardwareReadyType: 'std_msgs/msg/Bool',
  action: '/cube/execute_solution',
  actionType: 'system_interfaces/action/ExecuteCubeSolution',
  workflow: 'two_hand_layer_turn_v1',
};
const FACE_ORDER = 'URFDLB';
const FACE_START = Object.fromEntries([...FACE_ORDER].map((face, index) => [face, index * 9]));
const FACE_NORMAL = {
  U: [0, 1, 0], R: [1, 0, 0], F: [0, 0, 1],
  D: [0, -1, 0], L: [-1, 0, 0], B: [0, 0, -1],
};
const FACE_COLOR = {
  U: '#e9edf4', R: '#ee6670', F: '#53c996',
  D: '#f4c95d', L: '#f39a57', B: '#6398ed',
};
const FACE_TEXT = { U: '윗면', R: '오른쪽 면', F: '앞면', D: '아랫면', L: '왼쪽 면', B: '뒷면' };
const STATE_LABEL = {
  0: '수신', 1: '실행 대기', 2: '검증', 3: '손 전환',
  4: '실행 중', 5: '완료', 6: '오류', 7: '취소',
};
const PRIMITIVE_LABEL = {
  orient_face_up_and_support: '대상 면 정렬 및 큐브 지지',
  grasp_upper_layer: '상단 레이어 파지',
  rotate_upper_layer: '상단 레이어 회전',
  release_upper_layer: '파지 해제',
};
const PREVIEW_MOVE_MS = 800;
const CUBE_DISPLAY_SCALE = 0.5;
const canvas = document.querySelector('#cube-canvas');
const ctx = canvas.getContext('2d');
const $ = (selector) => document.querySelector(selector);

let socket = null;
let requestNumber = 0;
let activeActionId = '';
let activeScanId = '';
let activeExecutionId = '';
let cameraRequestId = '';
let cameraRequestTimer = 0;
let cameraListRequestId = '';
let cameraListRequestTimer = 0;
let cameraIndices = [];
let cameraListKnown = false;
let selectedCameraIndex = -1;
let activeCameraIndex = -1;
let pendingCameraIndex = -1;
let cameraRequestEnabled = false;
let cameraRequestIndex = -1;
let cameraActive = false;
let cameraStateKnown = false;
let realMode = false;
let hardwareReady = false;
let hardwareReadyAt = 0;
let activeActionDryRun = true;
let pendingSolution = null;
let actionAckTimer = 0;
let currentSolution = null;
let cubies = [];
let previewMode = false;
let previewMoveIndex = 0;
let syncedMoveIndex = 0;
let lastStatusMove = 0;
let animation = null;
let previewTimer = 0;
let yaw = -0.62;
let pitch = 0.36;
let pointer = null;
let rxCount = 0;
let txCount = 0;
let lastRxAt = 0;
let lastTxAt = 0;
const topicSignals = {
  solution: { count: 0, at: 0 },
  execution: { count: 0, at: 0 },
};
const events = [];

function recordEvent(type, message) {
  const event = { at: new Date(), type, message };
  events.unshift(event);
  if (events.length > 100) events.pop();
  const body = $('#event-list');
  const row = document.createElement('tr');
  const time = document.createElement('td');
  const category = document.createElement('td');
  const description = document.createElement('td');
  time.textContent = event.at.toLocaleTimeString('ko-KR', { hour12: false });
  category.textContent = type;
  description.textContent = message;
  category.className = 'event-type';
  row.append(time, category, description);
  if (body.querySelector('.event-empty')) body.replaceChildren();
  body.prepend(row);
  while (body.children.length > 100) body.lastElementChild.remove();
  $('#event-count').textContent = `${events.length}건`;
}

function setConnection(state, label, detail) {
  const badge = $('#connection-state');
  badge.dataset.state = state;
  badge.querySelector('span').textContent = label;
  $('#connection-detail').textContent = detail;
  $('#connect-button').textContent = state === 'online' ? '연결 해제' : '연결';
  updateControls();
}

function send(payload, logMessage = '') {
  if (!socket || socket.readyState !== WebSocket.OPEN) throw new Error('rosbridge에 연결되어 있지 않습니다.');
  const serialized = JSON.stringify(payload);
  socket.send(serialized);
  txCount += 1;
  lastTxAt = Date.now();
  updateSignals();
  if (logMessage) recordEvent('송신', logMessage);
}

function subscribeTopics() {
  send({ op: 'subscribe', id: 'monitor-cube-solution', topic: ROS.solutionTopic, type: ROS.solutionType, throttle_rate: 0, queue_length: 1 });
  send({ op: 'subscribe', id: 'monitor-execution-status', topic: ROS.executionTopic, type: ROS.executionType, throttle_rate: 0, queue_length: 10 });
  send({ op: 'subscribe', id: 'monitor-camera-active', topic: ROS.cameraStateTopic, type: ROS.cameraStateType, throttle_rate: 0, queue_length: 1 });
  send({ op: 'subscribe', id: 'monitor-hardware-ready', topic: ROS.hardwareReadyTopic, type: ROS.hardwareReadyType, throttle_rate: 0, queue_length: 1 });
  requestCameraList();
  $('#solution-signal-detail').textContent = 'CubeSolution · 구독 요청 전송';
  $('#execution-signal-detail').textContent = 'CubeExecutionStatus · 구독 요청 전송';
  recordEvent('ROS', '풀이 및 실행 상태 토픽 구독을 요청했습니다.');
}

function connect(url) {
  if (socket && socket.readyState < WebSocket.CLOSING) socket.close(1000, '재연결');
  setConnection('connecting', '연결 중', `${url} 연결 시도 중`);
  recordEvent('ROS', `${url} 연결을 시도합니다.`);
  const ws = new WebSocket(url);
  socket = ws;
  ws.addEventListener('open', () => {
    if (socket !== ws) return;
    setConnection('online', '연결됨', `${url} · 토픽 구독 준비 완료`);
    $('#connection-age').textContent = '연결 유지';
    recordEvent('ROS', 'rosbridge WebSocket 연결이 열렸습니다.');
    subscribeTopics();
  });
  ws.addEventListener('message', (event) => {
    if (socket !== ws) return;
    rxCount += 1;
    lastRxAt = Date.now();
    updateSignals();
    let message;
    try { message = JSON.parse(event.data); }
    catch { recordEvent('오류', 'JSON 형식이 아닌 rosbridge 신호를 받았습니다.'); return; }
    handleRosMessage(message);
  });
  ws.addEventListener('error', () => {
    if (socket !== ws) return;
    setConnection('error', '연결 오류', 'rosbridge 실행 상태와 WebSocket 주소를 확인하세요.');
    recordEvent('오류', 'WebSocket 통신 오류가 발생했습니다.');
  });
  ws.addEventListener('close', (event) => {
    if (socket !== ws) return;
    clearTimeout(actionAckTimer);
    clearTimeout(cameraRequestTimer);
    clearTimeout(cameraListRequestTimer);
    cameraRequestTimer = 0;
    cameraListRequestTimer = 0;
    cameraRequestId = '';
    cameraListRequestId = '';
    cameraRequestEnabled = false;
    cameraRequestIndex = -1;
    pendingCameraIndex = -1;
    cameraActive = false;
    activeCameraIndex = -1;
    cameraListKnown = false;
    cameraIndices = [];
    selectedCameraIndex = -1;
    hardwareReady = false;
    hardwareReadyAt = 0;
    realMode = false;
    socket = null;
    setConnection('offline', '연결 끊김', `WebSocket 연결이 종료되었습니다 · 코드 ${event.code}`);
    $('#connection-age').textContent = '끊김';
    $('#solution-signal').textContent = '끊김';
    $('#execution-signal').textContent = '끊김';
    $('#solution-signal-detail').textContent = '다시 연결하면 구독이 복구됩니다.';
    $('#execution-signal-detail').textContent = '다시 연결하면 구독이 복구됩니다.';
    $('#camera-state').textContent = 'ROS 연결 끊김 · 카메라 상태 확인 불가';
    renderCameraChoices();
    updateModeControl();
    recordEvent('ROS', `rosbridge 연결 종료 · 코드 ${event.code}`);
    if (activeActionId) {
      activeActionId = '';
      activeScanId = '';
      setExecutionState('error', '연결 종료', '실행 중 연결이 끊겨 액션 상태를 확인할 수 없습니다.');
    }
    updateControls();
  });
}

function handleRosMessage(message) {
  if (message.op === 'publish' && message.topic === ROS.solutionTopic) {
    topicSignals.solution.count += 1;
    topicSignals.solution.at = Date.now();
    updateSignals();
    receiveSolution(message.msg || {});
    return;
  }
  if (message.op === 'publish' && message.topic === ROS.executionTopic) {
    topicSignals.execution.count += 1;
    topicSignals.execution.at = Date.now();
    updateSignals();
    receiveExecutionStatus(message.msg || {});
    return;
  }
  if (message.op === 'publish' && message.topic === ROS.cameraStateTopic) {
    cameraActive = Boolean(message.msg?.data);
    cameraStateKnown = true;
    if (!cameraActive) activeCameraIndex = -1;
    updateCameraState();
    renderCameraChoices();
    return;
  }
  if (message.op === 'publish' && message.topic === ROS.hardwareReadyTopic) {
    updateHardwareReadiness(Boolean(message.msg?.data));
    return;
  }
  if (message.op === 'service_response' && message.id === cameraListRequestId) {
    clearTimeout(cameraListRequestTimer);
    cameraListRequestTimer = 0;
    cameraListRequestId = '';
    const values = message.values || {};
    if (message.result === false) {
      cameraListKnown = false;
      $('#camera-state').textContent = `카메라 목록 요청 실패 · ${String(message.values?.message || '카메라 관리 노드를 확인하세요.')}`;
      recordEvent('카메라 오류', $('#camera-state').textContent);
    } else {
      cameraIndices = Array.isArray(values.camera_indices) ? values.camera_indices.map(Number).filter((index) => Number.isInteger(index) && index >= 0 && index <= 2).slice(0, 3) : [];
      cameraActive = Boolean(values.active);
      activeCameraIndex = cameraActive ? Number(values.active_camera_index) : -1;
      cameraStateKnown = true;
      cameraListKnown = true;
      const preferredIndex = Number(values.preferred_camera_index);
      if (!cameraIndices.includes(selectedCameraIndex)) {
        selectedCameraIndex = activeCameraIndex >= 0
          ? activeCameraIndex
          : (cameraIndices.includes(preferredIndex) ? preferredIndex : (cameraIndices[0] ?? -1));
      }
      $('#camera-state').textContent = String(values.message || `카메라 ${cameraIndices.length}대 감지`);
      recordEvent('카메라', `카메라 검색 완료 · ${cameraIndices.length}대 감지${cameraIndices.length ? ` · index ${cameraIndices.join(', ')}` : ''}`);
      updateCameraState();
    }
    renderCameraChoices();
    updateControls();
    return;
  }
  if (message.op === 'service_response' && message.id === cameraRequestId) {
    clearTimeout(cameraRequestTimer);
    cameraRequestTimer = 0;
    cameraRequestId = '';
    const values = message.values || {};
    cameraActive = Boolean(values.active);
    cameraStateKnown = true;
    activeCameraIndex = cameraActive ? Number(values.active_camera_index ?? cameraRequestIndex) : -1;
    if (cameraRequestEnabled && cameraActive) selectedCameraIndex = activeCameraIndex;
    const requestEnabled = cameraRequestEnabled;
    cameraRequestEnabled = false;
    cameraRequestIndex = -1;
    updateCameraState();
    if (message.result === false || !values.success) {
      pendingCameraIndex = -1;
      const detail = String(values.message || '카메라 제어 서비스가 요청을 완료하지 못했습니다.');
      $('#camera-state').textContent = `오류 · ${detail}`;
      recordEvent('카메라 오류', detail);
    } else {
      recordEvent('카메라', String(values.message || (cameraActive ? '카메라가 시작되었습니다.' : '카메라가 중지되었습니다.')));
      if (!requestEnabled && pendingCameraIndex >= 0) {
        const nextIndex = pendingCameraIndex;
        pendingCameraIndex = -1;
        requestCamera(true, nextIndex);
      }
    }
    renderCameraChoices();
    updateControls();
    return;
  }
  if (message.op === 'action_feedback' && message.action === ROS.action) {
    if (message.id !== activeActionId) return;
    receiveActionFeedback(message.values || {});
    return;
  }
  if (message.op === 'action_result' && message.action === ROS.action) {
    receiveActionResult(message);
    return;
  }
  if (message.op === 'status') {
    const level = Number(message.level);
    const isError = level >= 2 || ['error', 'warning'].includes(String(message.level).toLowerCase());
    recordEvent(isError ? '브릿지 오류' : '브릿지', String(message.msg || message.message || '상태 신호'));
    if (isError) $('#connection-detail').textContent = String(message.msg || message.message || 'rosbridge에서 오류 신호를 보냈습니다.');
    if (isError && message.id === activeActionId) {
      clearTimeout(actionAckTimer);
      activeActionId = '';
      activeScanId = '';
      activeExecutionId = '';
      setExecutionState('error', '요청 오류', String(message.msg || message.message || '액션 서버가 요청을 거부했습니다.'));
    }
    return;
  }
  if (message.op === 'error') {
    recordEvent('브릿지 오류', String(message.msg || message.message || JSON.stringify(message)));
    if (message.id && message.id === cameraRequestId) {
      clearTimeout(cameraRequestTimer);
      cameraRequestTimer = 0;
      cameraRequestId = '';
      cameraRequestEnabled = false;
      cameraRequestIndex = -1;
      pendingCameraIndex = -1;
      $('#camera-state').textContent = `제어 요청 오류 · ${String(message.msg || '카메라 서비스를 확인하세요.')}`;
      updateControls();
    }
    if (message.id && message.id === cameraListRequestId) {
      clearTimeout(cameraListRequestTimer);
      cameraListRequestTimer = 0;
      cameraListRequestId = '';
      cameraListKnown = false;
      $('#camera-state').textContent = `카메라 목록 오류 · ${String(message.msg || '카메라 관리 노드를 확인하세요.')}`;
      renderCameraChoices();
      updateControls();
    }
    if (message.id && message.id === activeActionId) {
      clearTimeout(actionAckTimer);
      activeActionId = '';
      activeScanId = '';
      activeExecutionId = '';
      setExecutionState('error', '요청 오류', String(message.msg || '액션 요청이 거부되었습니다.'));
    }
  }
}

function receiveSolution(solution) {
  const error = validateSolution(solution);
  if (error) {
    $('#solution-state').dataset.state = 'error';
    $('#solution-state').textContent = '잘못된 풀이';
    $('#solution-signal').textContent = '오류';
    $('#solution-signal-detail').textContent = error;
    recordEvent('풀이 오류', error);
    updateControls();
    return;
  }
  const changed = currentSolution?.scan_id !== solution.scan_id;
  if (changed && activeActionId && activeScanId && solution.scan_id !== activeScanId) {
    pendingSolution = {
      scan_id: solution.scan_id,
      facelets: solution.facelets,
      moves: [...solution.moves],
      receivedAt: new Date(),
    };
    recordEvent('풀이 수신', `실행 중 새 풀이 ${solution.scan_id}를 받았습니다. 현재 실행이 끝난 뒤 표시합니다.`);
    return;
  }
  currentSolution = {
    scan_id: solution.scan_id,
    facelets: solution.facelets,
    moves: [...solution.moves],
    receivedAt: new Date(),
  };
  if (changed) {
    stopPreview();
    previewMode = false;
    $('#preview-toggle').checked = false;
    previewMoveIndex = 0;
    syncedMoveIndex = 0;
    lastStatusMove = 0;
    buildCube(solution.facelets);
    $('#canvas-empty').hidden = true;
    $('#cube-view-state').textContent = '풀이 수신 · 시작 상태';
  }
  $('#solution-state').dataset.state = 'ready';
  $('#solution-state').textContent = '풀이 준비';
  $('#solution-signal').textContent = '수신 완료';
  $('#solution-signal-detail').textContent = `${topicSignals.solution.count}건 · ${formatAge(Date.now() - topicSignals.solution.at)}`;
  $('#scan-id').textContent = solution.scan_id;
  $('#facelets').textContent = solution.facelets;
  $('#move-count').textContent = `${solution.moves.length}회`;
  renderMoveList();
  $('#preview-mode-label').textContent = 'ROS 피드백 동기화';
  recordEvent('풀이 수신', `scan_id ${solution.scan_id} · ${solution.moves.length}개 이동`);
  updateControls();
  drawFrame();
}

function validateSolution(solution) {
  if (!solution.scan_id || typeof solution.scan_id !== 'string') return 'scan_id가 없습니다.';
  if (typeof solution.facelets !== 'string' || solution.facelets.length !== 54) return 'facelets는 URFDLB 54자여야 합니다.';
  if ([...FACE_ORDER].some((face) => [...solution.facelets].filter((value) => value === face).length !== 9)) return '면 라벨은 URFDLB 각각 9개여야 합니다.';
  if (!Array.isArray(solution.moves) || solution.moves.some((move) => !/^[URFDLB](?:2|')?$/.test(move))) return '풀이 이동 표기가 올바르지 않습니다.';
  return '';
}

function receiveExecutionStatus(message) {
  $('#execution-signal').textContent = STATE_LABEL[message.state] || `상태 ${message.state}`;
  $('#execution-signal-detail').textContent = `${topicSignals.execution.count}건 · ${formatAge(Date.now() - topicSignals.execution.at)}`;
  if (!activeActionId || message.scan_id !== activeScanId) {
    recordEvent('ROS 상태', `${message.scan_id || 'scan 미지정'} · ${STATE_LABEL[message.state] || message.state}`);
    return;
  }
  const state = Number(message.state);
  if (!message.execution_id || (!activeExecutionId && [5, 6, 7].includes(state))) return;
  if (message.execution_id && !activeExecutionId) activeExecutionId = message.execution_id;
  if (message.execution_id && activeExecutionId && message.execution_id !== activeExecutionId) return;
  applyExecutionStatus(message, '토픽');
}

function receiveActionFeedback(feedback) {
  clearTimeout(actionAckTimer);
  const status = feedback.status || feedback;
  if (status.scan_id && activeScanId && status.scan_id !== activeScanId) return;
  if (status.execution_id) activeExecutionId = status.execution_id;
  applyExecutionStatus(status, '액션');
}

function applyExecutionStatus(status, source) {
  clearTimeout(actionAckTimer);
  const state = Number(status.state);
  const label = STATE_LABEL[state] || `상태 ${state}`;
  const active = state === 2 || state === 3 || state === 4;
  setExecutionState(active ? 'running' : (state === 5 ? 'success' : (state === 6 || state === 7 ? 'error' : 'idle')), label, status.message || '');
  const totalMoves = Number(status.total_moves || currentSolution?.moves.length || 0);
  const moveIndex = Number(status.move_index || 0);
  const totalSteps = Number(status.total_steps || 0);
  const stepIndex = Number(status.step_index || 0);
  $('#current-move').textContent = status.current_move || (state === 5 ? '완료' : '—');
  $('#current-step').textContent = totalSteps ? `${stepIndex} / ${totalSteps}` : '—';
  $('#progress-count').innerHTML = `${Math.max(0, moveIndex - (state === 5 ? 0 : 1))} <span>/ ${totalMoves}</span>`;
  const complete = state === 5 ? totalMoves : Math.max(0, moveIndex - 1);
  $('#progress-bar').style.width = `${totalMoves ? Math.min(100, complete / totalMoves * 100) : 0}%`;
  const handName = status.hand_id === 'leap_hand' ? 'LEAP Hand · 하단' : status.hand_id === 'custom_hand' ? 'Custom Hand · 상단' : '전환 중';
  $('#active-hand').textContent = status.hand_id ? handName : '—';
  $('#active-primitive').textContent = PRIMITIVE_LABEL[status.primitive_id] || status.primitive_id || '—';
  $('#workflow-stage').classList.toggle('is-active', active);
  $('#workflow-stage').querySelector('strong').textContent = status.primitive_id ? (PRIMITIVE_LABEL[status.primitive_id] || status.primitive_id) : label;
  $('#workflow-stage').querySelector('small').textContent = status.message || `${handName} · ${stepIndex}/${totalSteps} 단계`;
  if (status.error_code) $('#workflow-stage').classList.add('is-error');
  else $('#workflow-stage').classList.remove('is-error');
  recordEvent(source, `${label} · ${status.current_move || ''} · ${status.primitive_id ? (PRIMITIVE_LABEL[status.primitive_id] || status.primitive_id) : (status.message || '')}`.trim());

  if (!previewMode && currentSolution) {
    if (state === 4 && moveIndex > lastStatusMove && lastStatusMove > 0) {
      syncCubeThrough(Math.min(moveIndex - 1, currentSolution.moves.length));
    }
    lastStatusMove = Math.max(lastStatusMove, moveIndex);
    renderMoveList();
  }
}

function setExecutionState(state, label, message) {
  const badge = $('#execution-state');
  badge.dataset.state = state;
  badge.textContent = label;
  if (message) $('#execution-message').textContent = message;
  updateControls();
}

function receiveActionResult(message) {
  if (message.id !== activeActionId) return;
  clearTimeout(actionAckTimer);
  const result = message.values || {};
  const success = Boolean(result.success) && (Boolean(result.dry_run) === activeActionDryRun);
  const completedAsDryRun = activeActionDryRun;
  activeActionId = '';
  activeScanId = '';
  activeExecutionId = '';
  activeActionDryRun = true;
  if (success && currentSolution) {
    if (!previewMode) syncCubeThrough(Number(result.completed_moves ?? currentSolution.moves.length));
    const modeLabel = completedAsDryRun ? 'DRY-RUN 완료' : '실물 실행 완료';
    const modeDetail = completedAsDryRun ? '모터 출력 없음' : '실물 모드 실행 결과';
    setExecutionState('success', modeLabel, result.error_message || `${result.completed_moves}개 이동이 완료됐습니다.`);
    recordEvent('실행 완료', `${result.completed_moves}개 이동 · ${result.completed_steps}개 primitive 단계 · ${modeDetail}`);
    $('#progress-count').innerHTML = `${result.completed_moves} <span>/ ${currentSolution.moves.length}</span>`;
    $('#progress-bar').style.width = '100%';
  } else {
    const errorText = result.error_message || '액션이 정상 완료되지 않았습니다.';
    if (!previewMode && currentSolution && Number(result.completed_moves) > syncedMoveIndex) {
      syncCubeThrough(Number(result.completed_moves));
    }
    setExecutionState('error', result.error_code || '실행 중단', errorText);
    recordEvent('실행 오류', `${result.error_code || `action status ${message.status}`} · ${errorText}`);
  }
  if (realMode && !isHardwareReady()) {
    realMode = false;
    recordEvent('모드', '실물 준비 상태가 없어 다음 실행을 위해 dry-run 모드로 복귀했습니다.');
  }
  updateControls();
  if (pendingSolution) {
    const nextSolution = pendingSolution;
    pendingSolution = null;
    receiveSolution(nextSolution);
  }
}

function startAction() {
  if (!currentSolution) return;
  if (previewMode) {
    recordEvent('제어 차단', '미리보기 중에는 ROS 실행을 시작할 수 없습니다. 미리보기 토글을 끄세요.');
    return;
  }
  if (realMode && !isHardwareReady()) {
    realMode = false;
    updateModeControl();
    recordEvent('모드 차단', '하드웨어 준비 신호가 없거나 만료되어 dry-run으로 되돌렸습니다.');
    return;
  }
  if (realMode && !window.confirm('실물 로봇에 모터 명령을 전송합니다. 작업 공간과 비상 정지를 확인했습니까?')) {
    recordEvent('모드 확인', '사용자가 실물 실행을 취소했습니다.');
    return;
  }
  const id = `cube-ui-${Date.now()}-${++requestNumber}`;
  activeActionId = id;
  activeScanId = currentSolution.scan_id;
  activeExecutionId = '';
  activeActionDryRun = !realMode;
  pendingSolution = null;
  lastStatusMove = 0;
  syncedMoveIndex = 0;
  buildCube(currentSolution.facelets);
  $('#progress-count').innerHTML = `0 <span>/ ${currentSolution.moves.length}</span>`;
  $('#progress-bar').style.width = '0%';
  const dryRunForGoal = activeActionDryRun;
  setExecutionState('running', '액션 요청 중', `${dryRunForGoal ? 'dry_run=true' : 'dry_run=false'}로 /cube/execute_solution 요청을 보냈습니다.`);
  try {
    send({
      op: 'send_action_goal', id, action: ROS.action, action_type: ROS.actionType, feedback: true,
      args: {
        scan_id: currentSolution.scan_id,
        workflow_id: ROS.workflow,
        dry_run: dryRunForGoal,
        run_pretrained_policies: false,
      },
    }, `dry_run=${dryRunForGoal} · ${ROS.action} · ${currentSolution.scan_id}`);
    actionAckTimer = window.setTimeout(() => {
      if (!activeActionId || activeActionId !== id) return;
      if (!activeActionDryRun) {
        setExecutionState('error', '실물 상태 확인 필요', '실물 action 응답이 없습니다. 요청이 진행 중일 수 있으므로 action을 취소하고 로봇 상태를 확인하세요.');
        recordEvent('안전 상태', '실물 action 응답이 없어 중복 실행을 막기 위해 요청 상태를 유지합니다.');
        return;
      }
      activeActionId = '';
      activeScanId = '';
      activeExecutionId = '';
      setExecutionState('error', '응답 없음', '액션 응답이 없습니다. 큐브 실행 노드와 rosbridge 신호를 확인하세요.');
      recordEvent('오류', '액션 서버 응답 대기 시간 초과');
    }, 8000);
    recordEvent('모드', dryRunForGoal ? '요청에 dry_run=true를 명시했습니다. 실물 동작은 요청하지 않았습니다.' : '요청에 dry_run=false를 명시했습니다. 실물 동작 요청을 전송했습니다.');
  } catch (error) {
    activeActionId = '';
    activeScanId = '';
    activeExecutionId = '';
    setExecutionState('error', '요청 실패', error.message);
  }
  updateControls();
}

function cancelAction() {
  if (!activeActionId) return;
  try {
    send({ op: 'cancel_action_goal', id: activeActionId, action: ROS.action }, '실행 중인 큐브 풀이 액션 취소 요청');
    $('#execution-message').textContent = '취소 요청을 보냈습니다. 현재 primitive 경계에서 취소됩니다.';
  } catch (error) {
    recordEvent('오류', `취소 요청 실패 · ${error.message}`);
  }
}

function updateCameraState() {
  const status = $('#camera-state');
  const button = $('#camera-toggle');
  if (cameraActive) {
    button.classList.add('is-active');
    status.textContent = `카메라 ${activeCameraIndex >= 0 ? activeCameraIndex : '선택'} 촬영 중 · Space 촬영, R 재촬영, Q 종료`;
    button.textContent = '카메라 중지';
  } else {
    button.classList.remove('is-active');
    status.textContent = cameraStateKnown
      ? (selectedCameraIndex >= 0 ? `카메라 ${selectedCameraIndex} 선택 · 버튼을 눌러 촬영을 시작하세요.` : '감지된 카메라 중 하나를 선택하세요.')
      : '카메라 상태 확인 중';
    button.textContent = '선택 카메라 촬영';
  }
}

function requestCameraList() {
  if (!socket || socket.readyState !== WebSocket.OPEN || cameraListRequestId) return;
  const id = `camera-list-${Date.now()}-${++requestNumber}`;
  cameraListRequestId = id;
  $('#camera-state').textContent = '카메라 0~2 검색 중…';
  try {
    send({ op: 'call_service', id, service: ROS.cameraListService, args: {} }, '연결된 카메라 검색 요청');
    cameraListRequestTimer = window.setTimeout(() => {
      if (cameraListRequestId !== id) return;
      cameraListRequestId = '';
      cameraListRequestTimer = 0;
      cameraListKnown = false;
      $('#camera-state').textContent = '카메라 검색 시간 초과 · 카메라 관리 노드를 확인하세요.';
      recordEvent('카메라 오류', '카메라 목록 서비스 응답 시간 초과');
      renderCameraChoices();
      updateControls();
    }, 15000);
  } catch (error) {
    cameraListRequestId = '';
    $('#camera-state').textContent = `카메라 검색 실패 · ${error.message}`;
    recordEvent('카메라 오류', error.message);
  }
  updateControls();
}

function requestCamera(enabled, cameraIndex) {
  if (!socket || socket.readyState !== WebSocket.OPEN || cameraRequestId) return;
  const id = `camera-control-${Date.now()}-${++requestNumber}`;
  cameraRequestId = id;
  cameraRequestEnabled = enabled;
  cameraRequestIndex = cameraIndex;
  $('#camera-state').textContent = enabled ? `카메라 ${cameraIndex} 시작 요청 중…` : '카메라 중지 요청 중…';
  try {
    send({ op: 'call_service', id, service: ROS.cameraService, args: { enabled, camera_index: cameraIndex } }, enabled ? `카메라 ${cameraIndex} 촬영 시작 요청` : '카메라 촬영 중지 요청');
    cameraRequestTimer = window.setTimeout(() => {
      if (cameraRequestId !== id) return;
      cameraRequestId = '';
      cameraRequestTimer = 0;
      cameraRequestEnabled = false;
      cameraRequestIndex = -1;
      pendingCameraIndex = -1;
      $('#camera-state').textContent = '응답 시간 초과 · 카메라 관리 노드와 로그를 확인하세요.';
      recordEvent('카메라 오류', '카메라 제어 서비스 응답 시간 초과');
      updateControls();
    }, 12000);
  } catch (error) {
    cameraRequestId = '';
    cameraRequestEnabled = false;
    cameraRequestIndex = -1;
    pendingCameraIndex = -1;
    $('#camera-state').textContent = `카메라 제어 요청 실패 · ${error.message}`;
    recordEvent('카메라 오류', error.message);
  }
  updateControls();
}

function selectCamera(cameraIndex) {
  if (!cameraIndices.includes(cameraIndex) || cameraRequestId) return;
  selectedCameraIndex = cameraIndex;
  renderCameraChoices();
  if (cameraActive) {
    if (activeCameraIndex === cameraIndex) return;
    pendingCameraIndex = cameraIndex;
    requestCamera(false, activeCameraIndex);
    return;
  }
  requestCamera(true, cameraIndex);
}

function toggleCamera() {
  if (cameraActive) {
    pendingCameraIndex = -1;
    requestCamera(false, activeCameraIndex);
  } else if (selectedCameraIndex >= 0) {
    requestCamera(true, selectedCameraIndex);
  } else {
    requestCameraList();
  }
}

function renderCameraChoices() {
  const container = $('#camera-choices');
  if (!container) return;
  container.replaceChildren();
  if (!cameraListKnown) {
    const message = document.createElement('span');
    message.className = 'camera-empty';
    message.textContent = '카메라 목록 검색 전';
    container.append(message);
    return;
  }
  if (!cameraIndices.length) {
    const message = document.createElement('span');
    message.className = 'camera-empty';
    message.textContent = '감지된 카메라 없음 (index 0~2 검색 완료)';
    container.append(message);
    return;
  }
  for (const cameraIndex of cameraIndices) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'camera-choice';
    if (cameraIndex === selectedCameraIndex) button.classList.add('is-selected');
    if (cameraIndex === activeCameraIndex && cameraActive) button.classList.add('is-active');
    button.textContent = cameraIndex === activeCameraIndex && cameraActive ? `카메라 ${cameraIndex} · 촬영 중` : `카메라 ${cameraIndex}`;
    button.disabled = !socket || socket.readyState !== WebSocket.OPEN || Boolean(cameraRequestId);
    button.addEventListener('click', () => selectCamera(cameraIndex));
    container.append(button);
  }
}

function updateControls() {
  const connected = socket?.readyState === WebSocket.OPEN;
  $('#camera-refresh').disabled = !connected || Boolean(cameraListRequestId) || Boolean(cameraRequestId);
  $('#camera-toggle').disabled = !connected || Boolean(cameraRequestId) || (!cameraActive && selectedCameraIndex < 0);
  $('#execute-button').disabled = !connected || !currentSolution || Boolean(activeActionId) || previewMode;
  $('#cancel-button').disabled = !connected || !activeActionId;
  $('#preview-toggle').disabled = !currentSolution || Boolean(activeActionId);
  $('#copy-facelets').disabled = !currentSolution;
  renderCameraChoices();
  updateModeControl();
}

function isHardwareReady() {
  return hardwareReady && Date.now() - hardwareReadyAt <= 3000 && socket?.readyState === WebSocket.OPEN;
}

function updateHardwareReadiness(ready) {
  const wasReady = isHardwareReady();
  hardwareReady = ready;
  hardwareReadyAt = Date.now();
  const isReady = isHardwareReady();
  if (wasReady !== isReady) {
    recordEvent('하드웨어', isReady ? '실물 실행 준비 신호가 확인됐습니다.' : '실물 실행 준비 신호가 해제됐습니다.');
  }
  if (!isReady && realMode && !activeActionId) {
    realMode = false;
    recordEvent('모드', '실물 준비 상태가 해제되어 기본 dry-run 모드로 돌아왔습니다.');
  } else if (wasReady && !isReady && realMode && activeActionId) {
    try {
      send({ op: 'cancel_action_goal', id: activeActionId, action: ROS.action }, '실물 준비 신호 해제로 실행 취소 요청');
      recordEvent('안전 상태', '실물 준비 신호가 해제되어 현재 action 취소를 요청했습니다.');
    } catch (error) {
      recordEvent('안전 오류', `준비 신호 해제 후 action 취소 요청 실패 · ${error.message}`);
    }
  }
  updateModeControl();
}

function updateModeControl() {
  const control = $('#execution-mode-toggle');
  if (!control) return;
  const ready = isHardwareReady();
  const wrapper = control.closest('.mode-control');
  wrapper.dataset.mode = realMode ? 'real' : 'dry-run';
  wrapper.dataset.ready = String(ready);
  $('#execution-mode-label').textContent = realMode ? 'REAL' : 'DRY-RUN';
  $('#hardware-readiness').textContent = ready ? '하드웨어·안전 준비 완료' : '실물 준비 신호 없음 · 전환 잠김';
  $('#execute-button-label').textContent = realMode ? '실물 실행' : 'DRY-RUN 실행';
  $('#execute-button').disabled = socket?.readyState !== WebSocket.OPEN
    || !currentSolution
    || Boolean(activeActionId)
    || previewMode
    || (realMode && !ready);
  control.checked = realMode;
  control.disabled = !ready || Boolean(activeActionId);
  control.setAttribute('aria-label', ready
    ? `실행 모드: ${realMode ? '실물' : 'dry-run'}. 전환 가능`
    : '실행 모드: dry-run. 실물 준비 신호가 없어 전환 불가');
}

function setExecutionMode(useRealHardware) {
  if (useRealHardware && !isHardwareReady()) {
    realMode = false;
    recordEvent('모드 차단', '실물 준비 신호가 없거나 오래되어 실물 모드로 전환할 수 없습니다.');
  } else {
    realMode = Boolean(useRealHardware);
    recordEvent('모드', realMode ? '실물 모드를 선택했습니다. 실행 전 확인 대화상자가 표시됩니다.' : 'DRY-RUN 모드를 선택했습니다.');
  }
  updateModeControl();
}

function renderMoveList() {
  const list = $('#move-list');
  list.replaceChildren();
  if (!currentSolution?.moves.length) {
    const placeholder = document.createElement('span');
    placeholder.className = 'placeholder';
    placeholder.textContent = '풀이 수신 완료 · 이동이 없습니다.';
    list.append(placeholder);
    return;
  }
  const visibleIndex = previewMode ? previewMoveIndex : syncedMoveIndex;
  currentSolution.moves.forEach((move, index) => {
    const chip = document.createElement('span');
    chip.className = 'move-chip';
    if (index < visibleIndex) chip.classList.add('is-done');
    if (index === visibleIndex && (previewMode || activeActionId)) chip.classList.add('is-current');
    chip.textContent = move;
    chip.title = `${index + 1}번째 이동`;
    list.append(chip);
  });
}

function updateSignals() {
  if (hardwareReady && Date.now() - hardwareReadyAt > 3000) {
    hardwareReady = false;
    hardwareReadyAt = 0;
    if (realMode && !activeActionId) {
      realMode = false;
      recordEvent('모드', '실물 준비 heartbeat가 만료되어 기본 dry-run 모드로 돌아왔습니다.');
    } else if (realMode && activeActionId) {
      try {
        send({ op: 'cancel_action_goal', id: activeActionId, action: ROS.action }, '실물 준비 heartbeat 만료로 실행 취소 요청');
        recordEvent('안전 상태', '실물 준비 heartbeat가 만료되어 현재 action 취소를 요청했습니다.');
      } catch (error) {
        recordEvent('안전 오류', `준비 heartbeat 만료 후 action 취소 요청 실패 · ${error.message}`);
      }
    } else {
      recordEvent('하드웨어', '실물 준비 heartbeat가 3초 이상 수신되지 않았습니다.');
    }
  }
  $('#rx-count').textContent = rxCount.toLocaleString('ko-KR');
  $('#tx-count').textContent = txCount.toLocaleString('ko-KR');
  $('#rx-rate').textContent = lastRxAt ? `마지막 수신 ${formatAge(Date.now() - lastRxAt)} 전` : '마지막 수신 없음';
  $('#tx-rate').textContent = lastTxAt ? `마지막 송신 ${formatAge(Date.now() - lastTxAt)} 전` : '마지막 송신 없음';
  $('#solution-signal').textContent = topicSignals.solution.count ? '수신 중' : (socket ? '구독 중' : '대기');
  $('#solution-signal-detail').textContent = topicSignals.solution.count ? `${topicSignals.solution.count}건 · ${formatAge(Date.now() - topicSignals.solution.at)} 전` : (socket ? 'CubeSolution · 메시지 대기' : 'CubeSolution · 연결 전');
  $('#execution-signal').textContent = topicSignals.execution.count ? '수신 중' : (socket ? '구독 중' : '대기');
  $('#execution-signal-detail').textContent = topicSignals.execution.count ? `${topicSignals.execution.count}건 · ${formatAge(Date.now() - topicSignals.execution.at)} 전` : (socket ? 'CubeExecutionStatus · 메시지 대기' : 'CubeExecutionStatus · 연결 전');
  updateModeControl();
}

function formatAge(milliseconds) {
  if (milliseconds < 1000) return '방금';
  if (milliseconds < 60000) return `${Math.floor(milliseconds / 1000)}초`;
  return `${Math.floor(milliseconds / 60000)}분`;
}

function buildCube(facelets) {
  cubies = [];
  const readSticker = (face, x, y, z) => {
    let row; let column;
    if (face === 'F') { row = 1 - y; column = x + 1; }
    else if (face === 'B') { row = 1 - y; column = 1 - x; }
    else if (face === 'R') { row = 1 - y; column = 1 - z; }
    else if (face === 'L') { row = 1 - y; column = z + 1; }
    else if (face === 'U') { row = z + 1; column = x + 1; }
    else { row = 1 - z; column = x + 1; }
    return facelets[FACE_START[face] + row * 3 + column];
  };
  for (const x of [-1, 0, 1]) for (const y of [-1, 0, 1]) for (const z of [-1, 0, 1]) {
    const stickers = [];
    if (z === 1) stickers.push({ normal: [0, 0, 1], label: readSticker('F', x, y, z) });
    if (z === -1) stickers.push({ normal: [0, 0, -1], label: readSticker('B', x, y, z) });
    if (x === 1) stickers.push({ normal: [1, 0, 0], label: readSticker('R', x, y, z) });
    if (x === -1) stickers.push({ normal: [-1, 0, 0], label: readSticker('L', x, y, z) });
    if (y === 1) stickers.push({ normal: [0, 1, 0], label: readSticker('U', x, y, z) });
    if (y === -1) stickers.push({ normal: [0, -1, 0], label: readSticker('D', x, y, z) });
    cubies.push({ position: [x, y, z], stickers });
  }
  drawFrame();
}

function rotateVector(vector, axis, angle) {
  const cosine = Math.cos(angle); const sine = Math.sin(angle);
  const dot = vector[0] * axis[0] + vector[1] * axis[1] + vector[2] * axis[2];
  const cross = [
    axis[1] * vector[2] - axis[2] * vector[1],
    axis[2] * vector[0] - axis[0] * vector[2],
    axis[0] * vector[1] - axis[1] * vector[0],
  ];
  return vector.map((value, i) => value * cosine + cross[i] * sine + axis[i] * dot * (1 - cosine));
}

function moveAngle(move) {
  if (move.endsWith('2')) return -Math.PI;
  if (move.endsWith("'")) return Math.PI / 2;
  return -Math.PI / 2;
}

function startMoveAnimation(move, onComplete) {
  const axis = FACE_NORMAL[move[0]];
  animation = { move, axis, angle: moveAngle(move), started: performance.now(), duration: PREVIEW_MOVE_MS, onComplete };
}

function commitMove(move) {
  const axis = FACE_NORMAL[move[0]];
  const angle = moveAngle(move);
  for (const cubie of cubies) {
    const inLayer = cubie.position[0] * axis[0] + cubie.position[1] * axis[1] + cubie.position[2] * axis[2] > 0.5;
    if (!inLayer) continue;
    cubie.position = rotateVector(cubie.position, axis, angle).map((value) => Math.round(value));
    cubie.stickers = cubie.stickers.map((sticker) => ({ ...sticker, normal: rotateVector(sticker.normal, axis, angle).map((value) => Math.round(value)) }));
  }
}

function stopPreview() {
  clearTimeout(previewTimer);
  previewTimer = 0;
  animation = null;
}

function setPreviewMode(enabled) {
  if (!currentSolution) return;
  previewMode = enabled;
  stopPreview();
  if (enabled) {
    previewMoveIndex = 0;
    buildCube(currentSolution.facelets);
    $('#preview-mode-label').textContent = 'GUI 전용 · 이동당 0.8초';
    $('#cube-view-state').textContent = '풀이 미리보기 · 실물 제어 없음';
    $('#execution-message').textContent = '미리보기는 화면 안에서만 재생되며 ROS 실행 요청을 보내지 않습니다.';
    recordEvent('미리보기', 'GUI 전용 고정 속도(이동당 0.8초) 재생을 시작했습니다.');
    previewNextMove();
  } else {
    $('#preview-mode-label').textContent = 'ROS 피드백 동기화';
    $('#cube-view-state').textContent = 'ROS 실행 피드백 동기화';
    buildCube(currentSolution.facelets);
    for (let index = 0; index < syncedMoveIndex; index += 1) commitMove(currentSolution.moves[index]);
    $('#execution-message').textContent = activeActionId ? 'ROS 액션 피드백에 맞춰 진행 상태를 표시합니다.' : '액션 서버가 준비되면 풀이를 dry-run할 수 있습니다.';
    recordEvent('미리보기', 'ROS 피드백 동기화 모드로 돌아왔습니다.');
    renderMoveList();
    drawFrame();
  }
  updateControls();
}

function previewNextMove() {
  if (!previewMode || !currentSolution) return;
  if (previewMoveIndex >= currentSolution.moves.length) {
    $('#cube-view-state').textContent = '시뮬레이션 풀이 완료';
    $('#current-move').textContent = '완료';
    $('#progress-count').innerHTML = `${currentSolution.moves.length} <span>/ ${currentSolution.moves.length}</span>`;
    $('#progress-bar').style.width = '100%';
    renderMoveList();
    recordEvent('미리보기', '전체 풀이 수열의 화면 시뮬레이션이 끝났습니다.');
    return;
  }
  const move = currentSolution.moves[previewMoveIndex];
  $('#current-move').textContent = move;
  $('#current-step').textContent = `${previewMoveIndex + 1} / ${currentSolution.moves.length} · 시각화`;
  $('#progress-count').innerHTML = `${previewMoveIndex} <span>/ ${currentSolution.moves.length}</span>`;
  $('#progress-bar').style.width = `${previewMoveIndex / currentSolution.moves.length * 100}%`;
  renderMoveList();
  startMoveAnimation(move, () => {
    previewMoveIndex += 1;
    $('#progress-count').innerHTML = `${previewMoveIndex} <span>/ ${currentSolution.moves.length}</span>`;
    $('#progress-bar').style.width = `${previewMoveIndex / currentSolution.moves.length * 100}%`;
    renderMoveList();
    previewTimer = setTimeout(previewNextMove, 80);
  });
}

function syncCubeThrough(moveCount) {
  if (!currentSolution || previewMode) return;
  const target = Math.max(syncedMoveIndex, Math.min(moveCount, currentSolution.moves.length));
  if (target === syncedMoveIndex) return;
  while (syncedMoveIndex < target) {
    commitMove(currentSolution.moves[syncedMoveIndex]);
    syncedMoveIndex += 1;
  }
  $('#cube-view-state').textContent = `ROS 피드백 · ${syncedMoveIndex}/${currentSolution.moves.length} 이동 완료`;
  renderMoveList();
  drawFrame();
}

function faceBasis(normal) {
  const key = normal.join(',');
  const bases = {
    '0,0,1': { right: [1, 0, 0], up: [0, 1, 0] },
    '0,0,-1': { right: [-1, 0, 0], up: [0, 1, 0] },
    '1,0,0': { right: [0, 0, -1], up: [0, 1, 0] },
    '-1,0,0': { right: [0, 0, 1], up: [0, 1, 0] },
    '0,1,0': { right: [1, 0, 0], up: [0, 0, -1] },
    '0,-1,0': { right: [1, 0, 0], up: [0, 0, 1] },
  };
  return bases[key];
}

function viewTransform(point) {
  const cy = Math.cos(yaw); const sy = Math.sin(yaw);
  const cp = Math.cos(pitch); const sp = Math.sin(pitch);
  const x = point[0] * cy + point[2] * sy;
  const z1 = -point[0] * sy + point[2] * cy;
  return [x, point[1] * cp - z1 * sp, point[1] * sp + z1 * cp];
}

function project(point, width, height) {
  const transformed = viewTransform(point.map((value) => value * CUBE_DISPLAY_SCALE));
  const distance = 7.2 - transformed[2];
  const focal = Math.min(width, height) * 2.8;
  return { x: width / 2 + transformed[0] * focal / distance, y: height * 0.49 - transformed[1] * focal / distance, depth: transformed[2] };
}

function makeQuad(center, normal, basis, half) {
  const r = basis.right.map((value) => value * half);
  const u = basis.up.map((value) => value * half);
  const add = (a, b) => a.map((value, i) => value + b[i]);
  const subtract = (a, b) => a.map((value, i) => value - b[i]);
  return [add(subtract(center, r), u), add(add(center, r), u), add(add(center, r), negate(u)), add(subtract(center, r), negate(u))];
}
function negate(vector) { return vector.map((value) => -value); }

function drawPolygon(points, fill, stroke, lineWidth) {
  ctx.beginPath();
  ctx.moveTo(points[0].x, points[0].y);
  for (let i = 1; i < points.length; i += 1) ctx.lineTo(points[i].x, points[i].y);
  ctx.closePath();
  ctx.fillStyle = fill;
  ctx.fill();
  if (stroke) { ctx.lineWidth = lineWidth; ctx.strokeStyle = stroke; ctx.stroke(); }
}

function drawFrame(now = performance.now()) {
  const bounds = canvas.getBoundingClientRect();
  if (bounds.width < 2 || bounds.height < 2) return;
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const pixelWidth = Math.round(bounds.width * dpr); const pixelHeight = Math.round(bounds.height * dpr);
  if (canvas.width !== pixelWidth || canvas.height !== pixelHeight) { canvas.width = pixelWidth; canvas.height = pixelHeight; }
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  const width = bounds.width; const height = bounds.height;
  ctx.fillStyle = '#252722'; ctx.fillRect(0, 0, width, height);

  const shapes = [];
  let animationAngle = 0;
  let animatingLayer = null;
  if (animation) {
    const fraction = Math.min(1, (now - animation.started) / animation.duration);
    const eased = fraction < 0.5 ? 4 * fraction ** 3 : 1 - ((-2 * fraction + 2) ** 3) / 2;
    animationAngle = animation.angle * eased;
    animatingLayer = { axis: animation.axis, fraction };
  }

  for (const cubie of cubies) {
    const inLayer = animatingLayer && dot(cubie.position, animatingLayer.axis) > 0.5;
    const position = inLayer ? rotateVector(cubie.position, animatingLayer.axis, animationAngle) : cubie.position;
    for (const sticker of cubie.stickers) {
      const baseBasis = faceBasis(sticker.normal);
      const normal = inLayer ? rotateVector(sticker.normal, animatingLayer.axis, animationAngle) : sticker.normal;
      const basis = inLayer ? {
        right: rotateVector(baseBasis.right, animatingLayer.axis, animationAngle),
        up: rotateVector(baseBasis.up, animatingLayer.axis, animationAngle),
      } : baseBasis;
      const normalView = viewTransform(normal);
      if (normalView[2] <= 0.02) continue;
      const center = position.map((value, index) => value + normal[index] * 0.505);
      const tileCenter = position.map((value, index) => value + normal[index] * 0.475);
      const tile = makeQuad(tileCenter, normal, basis, 0.49).map((point) => project(point, width, height));
      const front = makeQuad(center, normal, basis, 0.42).map((point) => project(point, width, height));
      const depth = tile.reduce((sum, point) => sum + point.depth, 0) / tile.length;
      shapes.push({ depth, tile, front, label: sticker.label });
    }
  }
  shapes.sort((a, b) => a.depth - b.depth);
  for (const shape of shapes) {
    drawPolygon(shape.tile, '#393b35', '#6e7068', 1);
    drawPolygon(shape.front, FACE_COLOR[shape.label] || '#aab5bf', '#252722', 1.5);
    const centerX = shape.front.reduce((sum, point) => sum + point.x, 0) / shape.front.length;
    const centerY = shape.front.reduce((sum, point) => sum + point.y, 0) / shape.front.length;
    ctx.fillStyle = '#253238';
    ctx.font = `700 ${Math.max(12, Math.min(18, width * 0.026))}px 'Bithumb Gothic', sans-serif`;
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.fillText(shape.label, centerX, centerY);
  }

  if (animation && animatingLayer?.fraction >= 1) {
    const finished = animation;
    animation = null;
    commitMove(finished.move);
    finished.onComplete?.();
  }
  requestAnimationFrame(drawFrame);
}

function dot(left, right) { return left[0] * right[0] + left[1] * right[1] + left[2] * right[2]; }

canvas.addEventListener('pointerdown', (event) => {
  if (animation) return;
  pointer = { x: event.clientX, y: event.clientY, id: event.pointerId };
  canvas.setPointerCapture(event.pointerId);
});
canvas.addEventListener('pointermove', (event) => {
  if (!pointer || pointer.id !== event.pointerId) return;
  yaw += (event.clientX - pointer.x) * 0.009;
  pitch = Math.max(-0.9, Math.min(0.9, pitch + (event.clientY - pointer.y) * 0.008));
  pointer.x = event.clientX; pointer.y = event.clientY;
});
canvas.addEventListener('pointerup', () => { pointer = null; });
canvas.addEventListener('pointercancel', () => { pointer = null; });

$('#connection-form').addEventListener('submit', (event) => {
  event.preventDefault();
  if (socket && socket.readyState < WebSocket.CLOSING) {
    socket.close(1000, '사용자 연결 해제');
    return;
  }
  const url = $('#ws-url').value.trim();
  if (!url.startsWith('ws://') && !url.startsWith('wss://')) {
    setConnection('error', '주소 오류', 'ws:// 또는 wss:// 주소를 입력하세요.');
    return;
  }
  localStorage.setItem('middleware-bridge-ws-url', url);
  connect(url);
});

$('#execute-button').addEventListener('click', startAction);
$('#cancel-button').addEventListener('click', cancelAction);
$('#camera-toggle').addEventListener('click', toggleCamera);
$('#camera-refresh').addEventListener('click', requestCameraList);
$('#preview-toggle').addEventListener('change', (event) => setPreviewMode(event.target.checked));
$('#execution-mode-toggle').addEventListener('change', (event) => setExecutionMode(event.target.checked));
$('#clear-events').addEventListener('click', () => {
  events.length = 0;
  $('#event-list').innerHTML = '<tr class="event-empty"><td colspan="3">아직 기록된 이벤트가 없습니다.</td></tr>';
  $('#event-count').textContent = '0건';
});
$('#copy-facelets').addEventListener('click', async () => {
  if (!currentSolution) return;
  try { await navigator.clipboard.writeText(currentSolution.facelets); recordEvent('GUI', '큐브 facelets를 클립보드에 복사했습니다.'); }
  catch { recordEvent('오류', '클립보드에 복사하지 못했습니다.'); }
});

const savedUrl = localStorage.getItem('middleware-bridge-ws-url');
if (savedUrl) $('#ws-url').value = savedUrl;
setConnection('offline', '연결 끊김', 'rosbridge WebSocket 연결 대기 중');
renderCameraChoices();
setExecutionState('idle', '실행 대기', '액션 서버가 준비되면 풀이를 dry-run할 수 있습니다.');
updateSignals();
requestAnimationFrame(drawFrame);
window.setInterval(updateSignals, 1000);
window.setTimeout(() => connect($('#ws-url').value.trim()), 0);
