<template>
  <main class="batch-view">
    <section class="batch-header">
      <div>
        <p class="eyebrow">24h 批量托管</p>
        <h1>直播间监听控制台</h1>
      </div>
      <div class="header-actions">
        <input ref="fileInput" class="file-input" type="file" accept=".csv,text/csv" @change="handleFileChange" />
        <button class="btn secondary" type="button" @click="pickCsv">导入 CSV</button>
        <button class="btn" type="button" :disabled="rooms.length === 0 || running" @click="startDaemon">开始托管</button>
        <button class="btn danger" type="button" :disabled="!running" @click="stopDaemon">停止托管</button>
        <a class="btn ghost" :href="exportExcelUrl" target="_blank" rel="noreferrer">导出 Excel</a>
        <a class="btn ghost" :href="exportConsoleUrl" target="_blank" rel="noreferrer">导出控制台</a>
      </div>
    </section>

    <section class="control-band">
      <label class="field">
        <span>转发地址</span>
        <input v-model="relayUrl" placeholder="ws://localhost:8765" />
      </label>
      <label class="field compact">
        <span>轮询秒数</span>
        <input v-model.number="pollIntervalSeconds" type="number" min="30" max="600" />
      </label>
      <label class="field compact">
        <span>并发上限</span>
        <input v-model.number="maxConcurrentRooms" type="number" min="1" max="50" />
      </label>
      <button class="btn secondary" type="button" :disabled="rooms.length === 0 || polling" @click="runPollCycle">
        立即轮询
      </button>
      <button class="btn ghost" type="button" :disabled="rooms.length === 0" @click="clearRooms">清空清单</button>
    </section>

    <section v-if="guardMessage" class="guard-band">
      {{ guardMessage }}
    </section>

    <section class="stats-grid">
      <article class="stat">
        <span>账号数</span>
        <strong>{{ rooms.length }}</strong>
      </article>
      <article class="stat">
        <span>监听中</span>
        <strong>{{ listeningCount }}</strong>
      </article>
      <article class="stat">
        <span>已开播</span>
        <strong>{{ liveCount }}</strong>
      </article>
      <article class="stat">
        <span>消息数</span>
        <strong>{{ totalMessages }}</strong>
      </article>
      <article class="stat">
        <span>下次轮询</span>
        <strong>{{ nextPollLabel }}</strong>
      </article>
    </section>

    <section class="log-panel">
      <div class="panel-title">
        <h2>托管状态</h2>
        <span>{{ running ? '运行中' : '未启动' }}</span>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>状态</th>
              <th>主播</th>
              <th>直播号</th>
              <th>分组</th>
              <th>标题/昵称</th>
              <th>弹幕</th>
              <th>最后消息</th>
              <th>最近检查</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="room in sortedRooms" :key="room.uid">
              <td>
                <span class="status-pill" :class="room.status">{{ statusText(room.status) }}</span>
              </td>
              <td>
                <div class="room-name">{{ room.name || room.nickname || '未命名' }}</div>
              </td>
              <td class="mono">{{ room.roomNum }}</td>
              <td>{{ room.group || '-' }}</td>
              <td>
                <div class="title-cell">{{ room.title || room.nickname || '-' }}</div>
                <small v-if="room.error">{{ room.error }}</small>
              </td>
              <td>
                <strong>{{ room.messageCount }}</strong>
                <small>聊天 {{ room.chatCount }}</small>
              </td>
              <td class="last-message">{{ room.lastMessage || '-' }}</td>
              <td>{{ formatTime(room.lastCheckedAt) }}</td>
              <td class="row-actions">
                <button class="icon-btn" type="button" :disabled="room.status === 'listening'" @click="checkOne(room)">查</button>
                <button class="icon-btn" type="button" :disabled="room.status === 'listening'" @click="startRoom(room)">连</button>
                <button class="icon-btn danger-text" type="button" :disabled="room.status !== 'listening'" @click="stopRoom(room, '手动停止')">
                  停
                </button>
              </td>
            </tr>
            <tr v-if="rooms.length === 0">
              <td class="empty" colspan="9">导入 CSV 后开始托管。CSV 可包含 room_num、live_url、name、group、priority 字段。</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </main>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, useTemplateRef, watch } from 'vue';
import { CastMethod, DyCast, DyCastCloseCode, RoomStatus, type DyLiveInfo, type DyMessage } from '@/core/dycast';
import { getLiveInfo } from '@/core/request';
import SkMessage from '@/components/Message';

type WatchStatus = 'idle' | 'checking' | 'offline' | 'waiting' | 'connecting' | 'listening' | 'ended' | 'error';

interface WatchRoom {
  uid: string;
  name: string;
  roomNum: string;
  liveUrl: string;
  group: string;
  priority: number;
  enabled: boolean;
  status: WatchStatus;
  nickname?: string;
  title?: string;
  roomId?: string;
  messageCount: number;
  chatCount: number;
  lastMessage?: string;
  lastCheckedAt?: number;
  connectedAt?: number;
  error?: string;
}

interface RuntimeRoom {
  cast?: DyCast;
  relay?: WebSocket;
  relayQueue: string[];
  messageIds: Set<string>;
}

const STORAGE_KEY = 'dycast.batch.rooms.v1';
const SETTINGS_KEY = 'dycast.batch.settings.v2';

const rooms = ref<WatchRoom[]>(loadRooms());
const running = ref(false);
const polling = ref(false);
const nextPollAt = ref<number | null>(null);
const clockTick = ref(Date.now());
const guardMessage = ref('');
const relayUrl = ref('ws://localhost:8765');
const exportBaseUrl = ref('http://localhost:8766');
const pollIntervalSeconds = ref(600);
const maxConcurrentRooms = ref(10);
const fileInputRef = useTemplateRef<HTMLInputElement>('fileInput');
const runtimes = new Map<string, RuntimeRoom>();
let pollTimer: number | undefined;
let countdownTimer: number | undefined;

loadSettings();

const sortedRooms = computed(() =>
  [...rooms.value].sort((a, b) => {
    if (a.status === 'listening' && b.status !== 'listening') return -1;
    if (b.status === 'listening' && a.status !== 'listening') return 1;
    return a.priority - b.priority || a.roomNum.localeCompare(b.roomNum);
  })
);
const listeningCount = computed(() => rooms.value.filter(room => room.status === 'listening').length);
const liveCount = computed(() => rooms.value.filter(room => room.status === 'listening' || room.status === 'waiting').length);
const totalMessages = computed(() => rooms.value.reduce((sum, room) => sum + room.messageCount, 0));
const nextPollLabel = computed(() => {
  clockTick.value;
  if (!running.value || !nextPollAt.value) return '-';
  const delta = Math.max(0, Math.ceil((nextPollAt.value - Date.now()) / 1000));
  return `${delta}s`;
});
const exportRoot = computed(() => exportBaseUrl.value.replace(/\/$/, ''));
const exportExcelUrl = computed(() => `${exportRoot.value}/export/messages.xlsx?category=chat`);
const exportConsoleUrl = computed(() => `${exportRoot.value}/`);

watch(
  rooms,
  () => {
    persistRooms();
  },
  { deep: true }
);
watch([relayUrl, exportBaseUrl, pollIntervalSeconds, maxConcurrentRooms], persistSettings);

function loadRooms(): WatchRoom[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as WatchRoom[];
    return parsed.map(room => ({
      ...room,
      status: room.status === 'listening' || room.status === 'connecting' || room.status === 'checking' ? 'idle' : room.status,
      messageCount: room.messageCount || 0,
      chatCount: room.chatCount || 0
    }));
  } catch {
    return [];
  }
}

function loadSettings() {
  try {
    const raw = localStorage.getItem(SETTINGS_KEY);
    if (!raw) return;
    const settings = JSON.parse(raw);
    relayUrl.value = settings.relayUrl || relayUrl.value;
    exportBaseUrl.value = settings.exportBaseUrl || exportBaseUrl.value;
    pollIntervalSeconds.value = Number(settings.pollIntervalSeconds || pollIntervalSeconds.value);
    maxConcurrentRooms.value = Number(settings.maxConcurrentRooms || maxConcurrentRooms.value);
  } catch {}
}

function persistRooms() {
  const serializable = rooms.value.map(room => ({ ...room, status: room.status === 'listening' ? 'idle' : room.status }));
  localStorage.setItem(STORAGE_KEY, JSON.stringify(serializable));
}

function persistSettings() {
  localStorage.setItem(
    SETTINGS_KEY,
    JSON.stringify({
      relayUrl: relayUrl.value,
      exportBaseUrl: exportBaseUrl.value,
      pollIntervalSeconds: pollIntervalSeconds.value,
      maxConcurrentRooms: maxConcurrentRooms.value
    })
  );
}

function pickCsv() {
  fileInputRef.value?.click();
}

async function handleFileChange(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  if (!file) return;
  const text = await file.text();
  const imported = parseRoomsCsv(text);
  mergeRooms(imported);
  input.value = '';
  SkMessage.success(`已导入 ${imported.length} 个直播号`);
}

function parseRoomsCsv(text: string): WatchRoom[] {
  const rows = parseCsv(text).filter(row => row.some(cell => cell.trim()));
  if (rows.length === 0) return [];

  const first = rows[0].map(normalizeHeader);
  const hasHeader = first.some(cell => ['room_num', 'live_url', 'name', 'group', 'priority'].includes(cell));
  const body = hasHeader ? rows.slice(1) : rows;
  const header = hasHeader ? first : [];

  return body
    .map((row, index) => {
      const get = (key: string, fallbackIndex: number) => {
        const idx = header.indexOf(key);
        return (idx >= 0 ? row[idx] : row[fallbackIndex] || '').trim();
      };
      const roomSource = get('room_num', 0) || get('live_url', 0);
      const roomNum = extractRoomNum(roomSource);
      if (!roomNum) return null;
      const name = get('name', 1);
      return createRoom({
        name,
        roomNum,
        liveUrl: get('live_url', 2) || `https://live.douyin.com/${roomNum}`,
        group: get('group', 3),
        priority: Number(get('priority', 4) || index + 1)
      });
    })
    .filter((room): room is WatchRoom => Boolean(room));
}

function parseCsv(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = '';
  let quoted = false;
  for (let i = 0; i < text.length; i += 1) {
    const char = text[i];
    const next = text[i + 1];
    if (char === '"' && quoted && next === '"') {
      cell += '"';
      i += 1;
    } else if (char === '"') {
      quoted = !quoted;
    } else if (char === ',' && !quoted) {
      row.push(cell);
      cell = '';
    } else if ((char === '\n' || char === '\r') && !quoted) {
      if (char === '\r' && next === '\n') i += 1;
      row.push(cell);
      rows.push(row);
      row = [];
      cell = '';
    } else {
      cell += char;
    }
  }
  row.push(cell);
  rows.push(row);
  return rows;
}

function normalizeHeader(value: string) {
  const lower = value.trim().toLowerCase();
  const map: Record<string, string> = {
    room: 'room_num',
    roomid: 'room_num',
    room_id: 'room_num',
    roomnum: 'room_num',
    '直播号': 'room_num',
    '房间号': 'room_num',
    url: 'live_url',
    liveurl: 'live_url',
    '直播间': 'live_url',
    '链接': 'live_url',
    '主播': 'name',
    nickname: 'name',
    '名称': 'name',
    '分组': 'group',
    '优先级': 'priority'
  };
  return map[lower] || lower;
}

function extractRoomNum(value: string) {
  const match = value.match(/live\.douyin\.com\/(\d+)/) || value.match(/(\d{8,20})/);
  return match?.[1] || '';
}

function createRoom(input: Pick<WatchRoom, 'name' | 'roomNum' | 'liveUrl' | 'group' | 'priority'>): WatchRoom {
  return {
    uid: `${input.roomNum}-${Date.now()}-${Math.random().toString(16).slice(2)}`,
    name: input.name,
    roomNum: input.roomNum,
    liveUrl: input.liveUrl,
    group: input.group,
    priority: input.priority || 999,
    enabled: true,
    status: 'idle',
    messageCount: 0,
    chatCount: 0
  };
}

function mergeRooms(imported: WatchRoom[]) {
  const byRoom = new Map(rooms.value.map(room => [room.roomNum, room]));
  for (const item of imported) {
    const existing = byRoom.get(item.roomNum);
    if (existing) {
      Object.assign(existing, {
        name: item.name || existing.name,
        liveUrl: item.liveUrl || existing.liveUrl,
        group: item.group || existing.group,
        priority: item.priority || existing.priority,
        enabled: true
      });
    } else {
      rooms.value.push(item);
    }
  }
}

function startDaemon() {
  guardMessage.value = '';
  running.value = true;
  SkMessage.success('批量托管已启动');
  void runPollCycle();
  startTimers();
}

function stopDaemon() {
  running.value = false;
  window.clearTimeout(pollTimer);
  window.clearInterval(countdownTimer);
  for (const room of rooms.value) stopRoom(room, '托管停止');
  nextPollAt.value = null;
  SkMessage.info('批量托管已停止');
}

function startTimers() {
  window.clearTimeout(pollTimer);
  window.clearInterval(countdownTimer);
  countdownTimer = window.setInterval(() => {
    clockTick.value = Date.now();
  }, 1000);
  scheduleNextPoll();
}

function scheduleNextPoll() {
  if (!running.value) return;
  const seconds = Math.max(30, Number(pollIntervalSeconds.value) || 60);
  nextPollAt.value = Date.now() + seconds * 1000;
  window.clearTimeout(pollTimer);
  pollTimer = window.setTimeout(() => {
    void runPollCycle();
    scheduleNextPoll();
  }, seconds * 1000);
}

async function runPollCycle() {
  if (polling.value || guardMessage.value) return;
  polling.value = true;
  try {
    const candidates = rooms.value
      .filter(room => room.enabled && !['listening', 'connecting', 'checking'].includes(room.status))
      .sort((a, b) => a.priority - b.priority);
    for (const room of candidates) {
      if (listeningCount.value >= maxConcurrentRooms.value) {
        if (room.status !== 'listening') room.status = 'waiting';
        continue;
      }
      await checkOne(room, true);
      await sleep(1800 + Math.floor(Math.random() * 1200));
    }
  } finally {
    polling.value = false;
  }
}

async function checkOne(room: WatchRoom, autoStart = false) {
  if (room.status === 'listening' || room.status === 'connecting') return;
  room.status = 'checking';
  room.error = '';
  room.lastCheckedAt = Date.now();
  try {
    const info = await getLiveInfo(room.roomNum);
    applyInfo(room, info);
    if (info.status === RoomStatus.LIVING) {
      room.status = 'waiting';
      if (autoStart && listeningCount.value < maxConcurrentRooms.value) await startRoom(room);
    } else {
      room.status = 'offline';
    }
  } catch (err) {
    room.status = 'error';
    const message = err instanceof Error ? err.message : String(err);
    room.error = message;
    if (message.includes('验证码') || message.includes('风控')) {
      guardMessage.value = '检测到抖音验证码/风控中间页，已暂停自动轮询。请先在浏览器完成验证，或等待一段时间后再开始托管。';
      running.value = false;
      window.clearTimeout(pollTimer);
      nextPollAt.value = null;
    }
  }
}

async function startRoom(room: WatchRoom) {
  if (room.status === 'listening' || room.status === 'connecting') return;
  room.status = 'connecting';
  room.error = '';
  const runtime: RuntimeRoom = { relayQueue: [], messageIds: new Set() };
  runtimes.set(room.uid, runtime);
  const cast = new DyCast(room.roomNum);
  runtime.cast = cast;

  cast.on('open', (_ev, info) => {
    applyInfo(room, info);
    room.status = 'listening';
    room.connectedAt = Date.now();
    openRelay(room, info);
  });
  cast.on('message', msgs => handleRoomMessages(room, msgs));
  cast.on('reconnect', () => {
    room.status = 'listening';
    room.error = '';
  });
  cast.on('reconnecting', count => {
    room.error = `重连中 ${count || 0}`;
  });
  cast.on('close', (code, reason) => {
    closeRelay(runtime);
    if (code === DyCastCloseCode.LIVE_END) {
      room.status = 'ended';
    } else if (code !== DyCastCloseCode.NORMAL) {
      room.status = 'error';
      room.error = reason || '连接关闭';
    } else {
      room.status = running.value ? 'offline' : 'idle';
    }
    runtimes.delete(room.uid);
  });
  cast.on('error', err => {
    room.error = err.message || '连接错误';
  });

  await cast.connect();
}

function stopRoom(room: WatchRoom, reason = '停止监听') {
  const runtime = runtimes.get(room.uid);
  if (!runtime) {
    if (room.status === 'listening' || room.status === 'connecting') room.status = 'idle';
    return;
  }
  closeRelay(runtime);
  runtime.cast?.close(DyCastCloseCode.NORMAL, reason);
  runtimes.delete(room.uid);
  room.status = running.value ? 'offline' : 'idle';
}

function openRelay(room: WatchRoom, info?: DyLiveInfo) {
  const runtime = runtimes.get(room.uid);
  if (!runtime) return;
  const relay = new WebSocket(relayUrl.value);
  runtime.relay = relay;
  relay.addEventListener('open', () => {
    const roomInfo = {
      ...info,
      roomNum: room.roomNum,
      liveUrl: room.liveUrl,
      roomId: info?.roomId || room.roomId,
      nickname: info?.nickname || room.nickname,
      title: info?.title || room.title
    };
    relay.send(JSON.stringify(roomInfo));
    for (const item of runtime.relayQueue.splice(0)) relay.send(item);
  });
  relay.addEventListener('error', () => {
    room.error = '转发连接错误';
  });
  relay.addEventListener('close', () => {
    if (room.status === 'listening' && running.value) {
      window.setTimeout(() => openRelay(room, info), 3000);
    }
  });
}

function closeRelay(runtime: RuntimeRoom) {
  if (runtime.relay && runtime.relay.readyState <= WebSocket.OPEN) {
    runtime.relay.close(1000, 'close room relay');
  }
  runtime.relay = undefined;
  runtime.relayQueue.length = 0;
}

function handleRoomMessages(room: WatchRoom, msgs: DyMessage[]) {
  const runtime = runtimes.get(room.uid);
  const fresh: Array<DyMessage & { roomNum: string; roomId?: string }> = [];
  for (const msg of msgs) {
    const msgId = `${msg.method || 'unknown'}-${msg.id || Math.random()}`;
    if (msg.id && runtime?.messageIds.has(msgId)) continue;
    if (msg.id) runtime?.messageIds.add(msgId);
    const enriched = { ...msg, roomNum: room.roomNum, roomId: room.roomId };
    fresh.push(enriched);
    room.messageCount += 1;
    if (msg.method === CastMethod.CHAT || msg.method === CastMethod.EMOJI_CHAT) {
      room.chatCount += 1;
      room.lastMessage = msg.content || '';
    }
    if (msg.room?.status && msg.room.status !== RoomStatus.LIVING) stopRoom(room, '主播下播');
  }
  if (fresh.length > 0) sendRelay(room, JSON.stringify(fresh));
}

function sendRelay(room: WatchRoom, data: string) {
  const runtime = runtimes.get(room.uid);
  if (!runtime) return;
  if (runtime.relay?.readyState === WebSocket.OPEN) {
    runtime.relay.send(data);
    return;
  }
  runtime.relayQueue.push(data);
  if (runtime.relayQueue.length > 100) runtime.relayQueue.shift();
}

function applyInfo(room: WatchRoom, info?: DyLiveInfo) {
  if (!info) return;
  room.roomId = info.roomId || room.roomId;
  room.nickname = info.nickname || room.nickname;
  room.title = info.title || room.title;
}

function clearRooms() {
  stopDaemon();
  rooms.value = [];
  localStorage.removeItem(STORAGE_KEY);
}

function statusText(status: WatchStatus) {
  const map: Record<WatchStatus, string> = {
    idle: '待命',
    checking: '检查中',
    offline: '未开播',
    waiting: '待连接',
    connecting: '连接中',
    listening: '监听中',
    ended: '已下播',
    error: '异常'
  };
  return map[status];
}

function formatTime(value?: number) {
  if (!value) return '-';
  return new Date(value).toLocaleTimeString('zh-CN', { hour12: false });
}

function sleep(ms: number) {
  return new Promise(resolve => window.setTimeout(resolve, ms));
}

onBeforeUnmount(() => {
  stopDaemon();
});
</script>

<style scoped lang="scss">
.batch-view {
  width: 100%;
  min-height: 100%;
  box-sizing: border-box;
  padding: 18px;
  background: #f4f6f5;
  color: #18211d;
}

.batch-header,
.control-band,
.stats-grid,
.log-panel {
  max-width: 1680px;
  margin: 0 auto 14px;
}

.batch-header,
.control-band,
.panel-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
}

.batch-header h1 {
  margin: 0;
  font-size: 24px;
  line-height: 1.2;
}

.eyebrow {
  margin: 0 0 4px;
  color: #66756d;
  font-size: 13px;
}

.header-actions,
.row-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.file-input {
  display: none;
}

.btn,
.icon-btn {
  border: 1px solid #9eb2a6;
  background: #1f7f52;
  color: #fff;
  border-radius: 6px;
  height: 34px;
  padding: 0 13px;
  font-size: 14px;
  cursor: pointer;
  text-decoration: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.btn:disabled,
.icon-btn:disabled {
  cursor: not-allowed;
  opacity: 0.45;
}

.btn.secondary {
  color: #214130;
  background: #e7eee9;
}

.btn.ghost {
  color: #214130;
  background: #fff;
}

.btn.danger {
  background: #b54848;
  border-color: #b54848;
}

.icon-btn {
  min-width: 34px;
  padding: 0 8px;
  background: #fff;
  color: #244033;
}

.danger-text {
  color: #b54848;
}

.control-band,
.log-panel {
  border: 1px solid #cfdbd4;
  background: #fff;
  border-radius: 8px;
  padding: 12px;
  box-sizing: border-box;
}

.guard-band {
  max-width: 1680px;
  margin: 0 auto 14px;
  border: 1px solid #efcaca;
  background: #fff2f2;
  color: #9a3838;
  border-radius: 8px;
  padding: 12px;
  box-sizing: border-box;
  font-size: 14px;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 5px;
  min-width: 260px;
  flex: 1;
}

.field.compact {
  min-width: 110px;
  max-width: 140px;
}

.field span {
  font-size: 12px;
  color: #66756d;
}

.field input {
  height: 34px;
  border: 1px solid #c3d0c8;
  border-radius: 6px;
  padding: 0 10px;
  color: #17221d;
  background: #fbfcfb;
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(120px, 1fr));
  gap: 10px;
}

.stat {
  border: 1px solid #cfdbd4;
  background: #fff;
  border-radius: 8px;
  padding: 12px;
}

.stat span,
td small {
  display: block;
  color: #66756d;
  font-size: 12px;
}

.stat strong {
  display: block;
  margin-top: 4px;
  font-size: 24px;
}

.panel-title h2 {
  margin: 0;
  font-size: 17px;
}

.panel-title span {
  color: #66756d;
  font-size: 13px;
}

.table-wrap {
  margin-top: 10px;
  overflow: auto;
  max-height: calc(100vh - 278px);
}

table {
  width: 100%;
  border-collapse: collapse;
  min-width: 1080px;
}

th,
td {
  text-align: left;
  border-bottom: 1px solid #e5ebe8;
  padding: 9px 8px;
  vertical-align: middle;
  font-size: 13px;
}

th {
  color: #53645c;
  font-weight: 600;
  background: #f7f9f8;
  position: sticky;
  top: 0;
  z-index: 1;
}

.status-pill {
  display: inline-flex;
  min-width: 58px;
  justify-content: center;
  border-radius: 999px;
  padding: 4px 8px;
  background: #eef2ef;
  color: #50635a;
  font-size: 12px;
}

.status-pill.listening {
  background: #dff3e7;
  color: #16683f;
}

.status-pill.connecting,
.status-pill.checking,
.status-pill.waiting {
  background: #fff2d8;
  color: #8a5a00;
}

.status-pill.error {
  background: #fde4e4;
  color: #a83c3c;
}

.room-name,
.title-cell,
.last-message {
  max-width: 260px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mono {
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
}

.empty {
  height: 120px;
  text-align: center;
  color: #66756d;
}

@media (max-width: 900px) {
  .batch-header,
  .control-band {
    align-items: stretch;
    flex-direction: column;
  }

  .header-actions {
    justify-content: flex-start;
  }

  .stats-grid {
    grid-template-columns: repeat(2, minmax(120px, 1fr));
  }

  .field,
  .field.compact {
    width: 100%;
    min-width: 0;
    max-width: none;
  }
}
</style>
