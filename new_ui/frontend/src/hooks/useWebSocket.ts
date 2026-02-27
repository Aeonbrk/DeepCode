import { useEffect, useRef, useCallback, useState } from 'react';
import type { WSMessage } from '../types/api';

interface UseWebSocketOptions {
  onMessage?: (message: WSMessage) => void;
  onOpen?: () => void;
  onClose?: () => void;
  onError?: (error: Event) => void;
  reconnect?: boolean;
  reconnectInterval?: number;
  maxReconnectAttempts?: number;
}

export function useWebSocket(
  url: string | null,
  options: UseWebSocketOptions = {}
) {
  const debugPayloads = import.meta.env.VITE_DEBUG_WS_PAYLOADS === '1';

  const {
    onMessage,
    onOpen,
    onClose,
    onError,
    reconnect = true,
    reconnectInterval = 3000,
    maxReconnectAttempts = 50,  // Increased for long-running workflows
  } = options;

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectAttemptsRef = useRef(0);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const shouldReconnectRef = useRef(true);

  // Use refs for callbacks to avoid triggering reconnection on callback changes
  const onMessageRef = useRef(onMessage);
  const onOpenRef = useRef(onOpen);
  const onCloseRef = useRef(onClose);
  const onErrorRef = useRef(onError);

  // Update refs when callbacks change
  useEffect(() => {
    onMessageRef.current = onMessage;
    onOpenRef.current = onOpen;
    onCloseRef.current = onClose;
    onErrorRef.current = onError;
  }, [onMessage, onOpen, onClose, onError]);

  const [isConnected, setIsConnected] = useState(false);

  const connect = useCallback(() => {
    if (!url) return;

    // Clean up existing connection
    if (wsRef.current) {
      wsRef.current.close();
    }

    shouldReconnectRef.current = true;

    const wsUrl = url.startsWith('ws')
      ? url
      : `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}${url}`;

    const ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      setIsConnected(true);
      reconnectAttemptsRef.current = 0;
      onOpenRef.current?.();
    };

    ws.onclose = () => {
      setIsConnected(false);
      onCloseRef.current?.();

      // Attempt reconnection only if allowed
      if (
        shouldReconnectRef.current &&
        reconnect &&
        reconnectAttemptsRef.current < maxReconnectAttempts
      ) {
        reconnectTimeoutRef.current = setTimeout(() => {
          reconnectAttemptsRef.current += 1;
          connect();
        }, reconnectInterval);
      }
    };

    ws.onerror = (error) => {
      onErrorRef.current?.(error);
    };

    ws.onmessage = (event) => {
      try {
        const message = JSON.parse(event.data) as WSMessage;
        if (import.meta.env.DEV) {
          if (debugPayloads) {
            console.log('[useWebSocket] Received:', message.type, message);
          } else {
            console.log('[useWebSocket] Received:', message.type);
          }
        }
        if (onMessageRef.current) {
          onMessageRef.current(message);
        } else if (import.meta.env.DEV) {
          console.warn('[useWebSocket] No onMessage handler registered!');
        }
      } catch (e) {
        if (import.meta.env.DEV && debugPayloads) {
          console.error('Failed to parse WebSocket message:', event.data, e);
        } else {
          console.error('Failed to parse WebSocket message:', e);
        }
      }
    };

    wsRef.current = ws;
  }, [url, reconnect, reconnectInterval, maxReconnectAttempts]);  // Removed callback dependencies

  const disconnect = useCallback(() => {
    shouldReconnectRef.current = false;
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
    }
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
  }, []);

  const sendMessage = useCallback((data: unknown) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(data));
    }
  }, []);

  useEffect(() => {
    if (url) {
      connect();
    } else {
      disconnect();
    }

    return () => {
      disconnect();
    };
  }, [url, connect, disconnect]);

  return {
    isConnected,
    sendMessage,
    connect,
    disconnect,
  };
}
