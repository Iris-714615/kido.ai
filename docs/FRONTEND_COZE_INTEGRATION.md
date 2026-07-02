# 前端集成 Coze 流式对话指南

## 后端 API 端点

### 1. 创建会话
```http
POST /api/v1/chat/sessions
Authorization: Bearer {token}
Content-Type: application/json

{
  "title": "新的对话"
}
```

**响应**:
```json
{
  "id": 1,
  "child_id": 1,
  "title": "新的对话",
  "last_message_at": null,
  "created_at": "2024-01-15T10:00:00Z",
  "updated_at": "2024-01-15T10:00:00Z"
}
```

### 2. 流式发送消息（推荐）

```http
POST /api/v1/chat/sessions/{session_id}/messages/stream
Authorization: Bearer {token}
Content-Type: application/json

{
  "content": "为什么天空是蓝色的？"
}
```

**响应**: `text/event-stream` 格式

```
data: {"type":"chunk","text":"小"}

data: {"type":"chunk","text":"探险家"}

data: {"type":"chunk","text":"，"}

data: {"type":"done","message_id":2,"session_id":1}
```

### 3. 非流式发送消息（备选）

```http
POST /api/v1/chat/sessions/{session_id}/messages
Authorization: Bearer {token}
Content-Type: application/json

{
  "content": "为什么天空是蓝色的？"
}
```

---

## Vue 3 + TypeScript 集成示例

### 1. 安装依赖

```bash
npm install event-source-polyfill
# 或
yarn add event-source-polyfill
```

### 2. 创建 API 服务

```typescript
// src/api/chat.ts
export interface ChatMessage {
  id: number
  session_id: number
  role: 'user' | 'assistant'
  content: string
  metadata_json: Record<string, any>
  created_at: string
}

export interface ChatSession {
  id: number
  child_id: number
  title: string
  last_message_at: string | null
  created_at: string
  updated_at: string
}

export interface StreamChunk {
  type: 'chunk' | 'done'
  text?: string
  message_id?: number
  session_id?: number
}

class ChatAPI {
  private baseURL: string
  private token: string | null = null

  constructor(baseURL: string = '/api/v1') {
    this.baseURL = baseURL
    this.token = localStorage.getItem('access_token')
  }

  private getHeaders(): Record<string, string> {
    return {
      'Authorization': `Bearer ${this.token || ''}`,
      'Content-Type': 'application/json',
    }
  }

  async createSession(title?: string): Promise<ChatSession> {
    const response = await fetch(`${this.baseURL}/chat/sessions`, {
      method: 'POST',
      headers: this.getHeaders(),
      body: JSON.stringify({ title }),
    })
    if (!response.ok) throw new Error('Failed to create session')
    return response.json()
  }

  async getSessions(): Promise<ChatSession[]> {
    const response = await fetch(`${this.baseURL}/chat/sessions`, {
      headers: this.getHeaders(),
    })
    if (!response.ok) throw new Error('Failed to get sessions')
    return response.json()
  }

  async sendMessage(sessionId: number, content: string): Promise<ChatMessage> {
    const response = await fetch(
      `${this.baseURL}/chat/sessions/${sessionId}/messages`,
      {
        method: 'POST',
        headers: this.getHeaders(),
        body: JSON.stringify({ content }),
      }
    )
    if (!response.ok) throw new Error('Failed to send message')
    return response.json()
  }

  async *streamMessage(
    sessionId: number,
    content: string,
    onChunk?: (text: string) => void
  ): AsyncGenerator<ChatMessage, void, unknown> {
    const response = await fetch(
      `${this.baseURL}/chat/sessions/${sessionId}/messages/stream`,
      {
        method: 'POST',
        headers: this.getHeaders(),
        body: JSON.stringify({ content }),
      }
    )

    if (!response.ok) {
      throw new Error('Failed to stream message')
    }

    const reader = response.body?.getReader()
    if (!reader) throw new Error('No response body')

    const decoder = new TextDecoder()
    let buffer = ''
    let fullText = ''

    try {
      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const data: StreamChunk = JSON.parse(line.slice(6))

            if (data.type === 'chunk' && data.text) {
              fullText += data.text
              onChunk?.(fullText)
            }

            if (data.type === 'done') {
              // 返回最终消息
              const messageResponse = await fetch(
                `${this.baseURL}/chat/messages/${data.message_id}`,
                { headers: this.getHeaders() }
              )
              if (messageResponse.ok) {
                yield await messageResponse.json()
              }
              return
            }
          }
        }
      }
    } finally {
      reader.releaseLock()
    }
  }
}

export const chatAPI = new ChatAPI()
```

### 3. 创建 Composables

```typescript
// src/composables/useChat.ts
import { ref, type Ref } from 'vue'
import { chatAPI, type ChatSession, type ChatMessage } from '@/api/chat'

export function useChat() {
  const sessions = ref<ChatSession[]>([])
  const currentSession = ref<ChatSession | null>(null)
  const messages = ref<ChatMessage[]>([])
  const isLoading = ref(false)
  const streamingText = ref('')

  // 加载会话列表
  async function loadSessions() {
    isLoading.value = true
    try {
      sessions.value = await chatAPI.getSessions()
    } finally {
      isLoading.value = false
    }
  }

  // 创建新会话
  async function createSession(title?: string) {
    const session = await chatAPI.createSession(title)
    sessions.value.unshift(session)
    currentSession.value = session
    messages.value = []
    return session
  }

  // 发送消息（非流式）
  async function sendMessage(content: string) {
    if (!currentSession.value) throw new Error('No active session')

    const userMessage: ChatMessage = {
      id: Date.now(),
      session_id: currentSession.value.id,
      role: 'user',
      content,
      metadata_json: {},
      created_at: new Date().toISOString(),
    }
    messages.value.push(userMessage)

    try {
      const assistantMessage = await chatAPI.sendMessage(
        currentSession.value.id,
        content
      )
      messages.value.push(assistantMessage)
      return assistantMessage
    } catch (error) {
      messages.value.pop()
      throw error
    }
  }

  // 流式发送消息
  async function sendMessageStream(
    content: string,
    onStream?: (text: string) => void
  ) {
    if (!currentSession.value) throw new Error('No active session')

    const userMessage: ChatMessage = {
      id: Date.now(),
      session_id: currentSession.value.id,
      role: 'user',
      content,
      metadata_json: {},
      created_at: new Date().toISOString(),
    }
    messages.value.push(userMessage)

    // 添加占位的助手消息
    const assistantMessage: ChatMessage = {
      id: Date.now() + 1,
      session_id: currentSession.value.id,
      role: 'assistant',
      content: '',
      metadata_json: {},
      created_at: new Date().toISOString(),
    }
    messages.value.push(assistantMessage)

    try {
      for await (const message of chatAPI.streamMessage(
        currentSession.value.id,
        content,
        onStream
      )) {
        assistantMessage.content = message.content
        assistantMessage.id = message.id
        assistantMessage.metadata_json = message.metadata_json
      }
      return assistantMessage
    } catch (error) {
      messages.value.pop()
      throw error
    }
  }

  return {
    sessions,
    currentSession,
    messages,
    isLoading,
    streamingText,
    loadSessions,
    createSession,
    sendMessage,
    sendMessageStream,
  }
}
```

### 4. 在组件中使用

```vue
<!-- src/components/ChatBox.vue -->
<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useChat } from '@/composables/useChat'

const {
  sessions,
  currentSession,
  messages,
  isLoading,
  streamingText,
  loadSessions,
  createSession,
  sendMessageStream,
} = useChat()

const inputText = ref('')
const messagesContainer = ref<HTMLElement>()

onMounted(() => {
  loadSessions()
})

async function handleSend() {
  if (!inputText.value.trim()) return

  const text = inputText.value
  inputText.value = ''

  // 使用流式发送
  await sendMessageStream(text, (fullText) => {
    streamingText.value = fullText
  })

  // 滚动到底部
  nextTick(() => {
    messagesContainer.value?.scrollTo({
      top: messagesContainer.value.scrollHeight,
      behavior: 'smooth',
    })
  })
}

async function startNewChat() {
  await createSession(`对话 ${new Date().toLocaleString()}`)
}
</script>

<template>
  <div class="chat-container">
    <!-- 会话列表侧边栏 -->
    <div class="sidebar">
      <button @click="startNewChat">新建对话</button>
      <div v-for="session in sessions" :key="session.id" class="session-item">
        {{ session.title }}
      </div>
    </div>

    <!-- 聊天主区域 -->
    <div class="chat-main">
      <div ref="messagesContainer" class="messages">
        <div
          v-for="msg in messages"
          :key="msg.id"
          :class="['message', msg.role]"
        >
          <div class="content">{{ msg.content }}</div>
        </div>
        <!-- 流式输出时的临时显示 -->
        <div v-if="streamingText" class="message assistant streaming">
          <div class="content">{{ streamingText }}</div>
        </div>
      </div>

      <!-- 输入区域 -->
      <div class="input-area">
        <textarea
          v-model="inputText"
          placeholder="输入你的问题..."
          @keydown.enter.exact.prevent="handleSend"
        />
        <button @click="handleSend" :disabled="isLoading">
          发送
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.chat-container {
  display: flex;
  height: 100vh;
}

.sidebar {
  width: 250px;
  border-right: 1px solid #eee;
  padding: 16px;
}

.chat-main {
  flex: 1;
  display: flex;
  flex-direction: column;
}

.messages {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
}

.message {
  margin-bottom: 16px;
  max-width: 70%;
}

.message.user {
  margin-left: auto;
  background: #e3f2fd;
}

.message.assistant {
  margin-right: auto;
  background: #f5f5f5;
}

.message.streaming .content {
  border-left: 3px solid #2196f3;
  padding-left: 8px;
}

.input-area {
  display: flex;
  gap: 8px;
  padding: 16px;
  border-top: 1px solid #eee;
}
</style>
```

---

## 纯 JavaScript 示例（无框架）

```javascript
// chat.js
class ChatClient {
  constructor(baseURL = '/api/v1') {
    this.baseURL = baseURL
    this.token = localStorage.getItem('access_token')
  }

  async createSession(title) {
    const res = await fetch(`${this.baseURL}/chat/sessions`, {
      method: 'POST',
      headers: this.getHeaders(),
      body: JSON.stringify({ title }),
    })
    return res.json()
  }

  async streamMessage(sessionId, content, onChunk, onDone) {
    const res = await fetch(
      `${this.baseURL}/chat/sessions/${sessionId}/messages/stream`,
      {
        method: 'POST',
        headers: this.getHeaders(),
        body: JSON.stringify({ content }),
      }
    )

    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let fullText = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          const data = JSON.parse(line.slice(6))
          if (data.type === 'chunk') {
            fullText += data.text
            onChunk?.(fullText)
          } else if (data.type === 'done') {
            onDone?.(data)
            return
          }
        }
      }
    }
  }

  getHeaders() {
    return {
      'Authorization': `Bearer ${this.token}`,
      'Content-Type': 'application/json',
    }
  }
}

// 使用示例
const chat = new ChatClient()

async function sendMessage(sessionId, text) {
  const messagesEl = document.getElementById('messages')

  // 添加用户消息
  messagesEl.innerHTML += `<div class="user">${text}</div>`

  // 添加助手占位
  const assistantEl = document.createElement('div')
  assistantEl.className = 'assistant streaming'
  messagesEl.appendChild(assistantEl)

  await chat.streamMessage(
    sessionId,
    text,
    (fullText) => {
      assistantEl.textContent = fullText
    },
    (data) => {
      console.log('Message completed:', data)
    }
  )
}
```

---

## 关键配置

### .env 配置

```env
# 启用 Coze 模式
AI_PROVIDER=coze

# Coze API Key
COZE_API_KEY=pat_xxxxxxxxxxxx

# Coze Bot ID（从 Coze 平台获取）
COZE_BOT_ID=7654142913093386294

# 用户 ID 前缀，用于区分不同儿童
COZE_USER_ID_PREFIX=kidoai-child-
```

### Coze 平台配置

1. 在 Coze 平台创建 Bot
2. 获取 Bot ID（从 URL 或设置中获取）
3. 配置 Prompt 和插件
4. 发布 Bot

---

## 数据流

```text
前端输入消息
    ↓
POST /api/v1/chat/sessions/{id}/messages/stream
    ↓
FastAPI 接收请求
    ↓
调用 stream_chat_reply()
    ↓
CozeAdapter.stream_chat_reply()
    ↓
coze.chat.stream() -> SSE 流
    ↓
逐 chunk 返回前端
    ↓
前端实时渲染
    ↓
完成后保存到数据库
```

---

## 注意事项

1. **SSE 格式**: 后端返回 `text/event-stream`，前端需要解析 SSE 格式
2. **Token 认证**: 确保请求头包含 `Authorization: Bearer {token}`
3. **错误处理**: 网络中断时需要断线重连机制
4. **取消请求**: 使用 `AbortController` 实现取消发送
5. **CORS**: 确保后端允许前端域名访问