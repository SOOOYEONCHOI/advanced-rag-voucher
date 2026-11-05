import { getAuthHeaders } from './http';
import { TEMPORARY_ERROR_MESSAGE } from '../constants/userMessages';

export const parseSSEStream = async function* (reader) {
  const decoder = new TextDecoder('utf-8');
  let buffer = '';

  const parseEvent = (rawEvent) => {
    const data = rawEvent
      .split(/\r?\n/)
      .filter((eventLine) => eventLine.startsWith('data:'))
      .map((eventLine) => eventLine.replace(/^data:\s?/, ''))
      .join('\n')
      .trim();

    if (!data) return null;

    if (data === '[DONE]') {
      return { type: 'done' };
    }

    try {
      return JSON.parse(data);
    } catch {
      return {
        type: 'error',
        message: TEMPORARY_ERROR_MESSAGE,
      };
    }
  };

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const events = buffer.split(/\r?\n\r?\n/);
    buffer = events.pop() || '';

    for (const rawEvent of events) {
      const event = parseEvent(rawEvent);
      if (!event) continue;
      yield event;
      if (event.type === 'done') {
        return;
      }
    }
  }

  buffer += decoder.decode();
  if (!buffer.trim()) return;

  const event = parseEvent(buffer);
  if (!event) return;
  yield event;
  if (event.type === 'done') {
    return;
  }
};

export const chatStreamApi = {
  async send(payload, { onEvent, signal } = {}) {
    const response = await fetch('/api/query/stream', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...getAuthHeaders(),
      },
      body: JSON.stringify(payload),
      signal,
    });

    if (!response.ok) {
      let message = `HTTP ${response.status}`;
      try {
        const errorData = await response.json();
        message = errorData.detail || errorData.message || message;
      } catch {
        /* ignore */
      }
      throw new Error(message);
    }

    if (!response.body) {
      throw new Error(TEMPORARY_ERROR_MESSAGE);
    }

    const reader = response.body.getReader();

    try {
      for await (const event of parseSSEStream(reader)) {
        await onEvent?.(event);
        if (event.type === 'done') break;
      }
    } finally {
      reader.releaseLock();
    }
  },
};
