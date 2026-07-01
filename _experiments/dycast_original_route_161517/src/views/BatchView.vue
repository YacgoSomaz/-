<template>
  <main class="batch-view">
    <section class="batch-header">
      <div>
        <p class="eyebrow">低并发手动监听</p>
        <h1>直播间手动监听台</h1>
      </div>
      <div class="header-actions">
        <button class="btn" type="button" :disabled="rooms.length === 0 || listeningCount >= maxConcurrentRooms" @click="startAvailableRooms">
          连接空闲房间
        </button>
        <button class="btn danger" type="button" :disabled="listeningCount === 0" @click="stopAllRooms">全部停止</button>
        <a class="btn ghost" :href="exportExcelUrl" target="_blank" rel="noreferrer">导出 Excel</a>
        <a class="btn ghost" :href="exportConsoleUrl" target="_blank" rel="noreferrer">导出控制台</a>
      </div>
    </section>

    <section class="control-band">
      <label class="field">
        <span>直播号或直播间链接</span>
        <input v-model.trim="manualRoomSource" placeholder="430322042715 或 https://live.douyin.com/..." @keydown.enter.prevent="addManualRoom" />
      </label>
      <label class="field compact">
        <span>主播备注</span>
        <input v-model.trim="manualName" placeholder="可选" @keydown.enter.prevent="addManualRoom" />
      </label>
      <label class="field compact">
        <span>分组</span>
        <input v-model.trim="manualGroup" placeholder="可选" @keydown.enter.prevent="addManualRoom" />
      </label>
      <button class="btn secondary" type="button" @click="addManualRoom">添加</button>
      <label class="field">
        <span>转发地址</span>
        <input v-model="relayUrl" placeholder="ws://localhost:8775" />
      </label>
      <label class="field compact">
        <span>并发上限</span>
        <input v-model.number="maxConcurrentRooms" type="number" min="1" max="5" />
      </label>
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
        <span>空闲</span>
        <strong>{{ idleCount }}</strong>
      </article>
      <article class="stat">
        <span>消息数</span>
        <strong>{{ totalMessages }}</strong>
      </article>
      <article class="stat">
        <span>并发上限</span>
        <strong>{{ maxConcurrentRooms }}</strong>
      </article>
    </section>

    <section class="log-panel">
      <div class="panel-title">
        <h2>监听状态</h2>
        <span>手动连接，不自动轮询</span>
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
              <th>连接时间</th>
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
              <td>{{ formatTime(room.connectedAt) }}</td>
              <td class="row-actions">
                <button class="icon-btn" type="button" :disabled="!canStartRoom(room)" @click="startRoom(room)">连</button>
                <button class="icon-btn danger-text" type="button" :disabled="room.status !== 'listening'" @click="stopRoom(room, '手动停止')">
                  停
                </button>
                <button class="icon-btn danger-text" type="button" :disabled="room.status === 'listening'" @click="removeRoom(room)">删</button>
              </td>
            </tr>
            <tr v-if="rooms.length === 0">
              <td class="empty" colspan="9">手动添加直播号后点击“连”。本页面不自动轮询开播状态。</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </main>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue';
import { CastMethod, DyCast, DyCastCloseCode, RoomStatus, type DyLiveInfo, type DyMessage } from '@/core/dycast';
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
const SETTINGS_KEY = 'dycast.batch.settings.original-route.v1';

const rooms = ref<WatchRoom[]>(loadRooms());
const guardMessage = ref('');
const relayUrl = ref('ws://localhost:8775');
const exportBaseUrl = ref('http://localhost:8776');
const maxConcurrentRooms = ref(3);
const manualRoomSource = ref('');
const manualName = ref('');
const manualGroup = ref('');
const runtimes = new Map<string, RuntimeRoom>();

loadSettings();

const sortedRooms = computed(() =>
  [...rooms.value].sort((a, b) => {
    if (a.status === 'listening' && b.status !== 'listening') return -1;
    if (b.status === 'listening' && a.status !== 'listening') return 1;
    return a.priority - b.priority || a.roomNum.localeCompare(b.roomNum);
  })
);
const listeningCount = computed(() => rooms.value.filter(room => room.status === 'listening').length);
const idleCount = computed(() => rooms.value.filter(room => ['idle', 'offline', 'ended', 'error'].includes(room.status)).length);
const totalMessages = computed(() => rooms.value.reduce((sum, room) => sum + room.messageCount, 0));
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
watch([relayUrl, exportBaseUrl, maxConcurrentRooms], persistSettings);

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
    maxConcurrentRooms.value = clampConcurrency(Number(settings.maxConcurrentRooms || maxConcurrentRooms.value));
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
      maxConcurrentRooms: clampConcurrency(maxConcurrentRooms.value)
    })
  );
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

function addManualRoom() {
  const roomNum = extractRoomNum(manualRoomSource.value);
  if (!roomNum) {
    SkMessage.error('请输入有效的直播号或直播间链接');
    return;
  }
  const existing = rooms.value.find(room => room.roomNum === roomNum);
  if (existing) {
    existing.name = manualName.value || existing.name;
    existing.group = manualGroup.value || existing.group;
    existing.enabled = true;
    SkMessage.info('直播号已存在，已更新备注');
  } else {
    rooms.value.push(
      createRoom({
        name: manualName.value,
        roomNum,
        liveUrl: `https://live.douyin.com/${roomNum}`,
        group: manualGroup.value,
        priority: rooms.value.length + 1
      })
    );
    SkMessage.success('已添加直播号');
  }
  manualRoomSource.value = '';
  manualName.value = '';
  manualGroup.value = '';
}

function clampConcurrency(value: number) {
  if (!Number.isFinite(value)) return 3;
  return Math.min(5, Math.max(1, Math.floor(value)));
}

function canStartRoom(room: WatchRoom) {
  return room.status !== 'listening' && room.status !== 'connecting' && listeningCount.value < clampConcurrency(maxConcurrentRooms.value);
}

async function startAvailableRooms() {
  const limit = clampConcurrency(maxConcurrentRooms.value);
  for (const room of sortedRooms.value) {
    if (listeningCount.value >= limit) break;
    if (canStartRoom(room)) await startRoom(room);
    await sleep(1500);
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
      room.status = 'idle';
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
  room.status = 'idle';
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
    if (room.status === 'listening') {
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
  stopAllRooms();
  rooms.value = [];
  localStorage.removeItem(STORAGE_KEY);
}

function removeRoom(room: WatchRoom) {
  stopRoom(room, '删除房间');
  rooms.value = rooms.value.filter(item => item.uid !== room.uid);
}

function stopAllRooms() {
  for (const room of rooms.value) stopRoom(room, '全部停止');
  SkMessage.info('已停止所有监听');
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
  stopAllRooms();
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
