import { useEffect, useCallback, useRef } from 'react';
import { useWebSocket } from './useWebSocket';
import { useWorkflowStore } from '../stores/workflowStore';
import { shallow } from 'zustand/shallow';
import type { WSMessage } from '../types/api';

export function useStreaming(taskId: string | null) {
  const isDev = import.meta.env.DEV;
  const debugPayloads = import.meta.env.VITE_DEBUG_STREAM_PAYLOADS === '1';

  const {
    status,
    updateProgress,
    setStatus,
    setResult,
    setError,
    appendStreamedCode,
    setCurrentFile,
    addGeneratedFile,
    addActivityLog,
    setPendingInteraction,
    clearInteraction,
  } = useWorkflowStore(
    (s) => ({
      status: s.status,
      updateProgress: s.updateProgress,
      setStatus: s.setStatus,
      setResult: s.setResult,
      setError: s.setError,
      appendStreamedCode: s.appendStreamedCode,
      setCurrentFile: s.setCurrentFile,
      addGeneratedFile: s.addGeneratedFile,
      addActivityLog: s.addActivityLog,
      setPendingInteraction: s.setPendingInteraction,
      clearInteraction: s.clearInteraction,
    }),
    shallow
  );

  // Track previous taskId to detect changes
  const prevTaskIdRef = useRef<string | null>(null);

  // Determine if finished based on store status (persisted state)
  const isFinished = status === 'completed' || status === 'error' || status === 'cancelled';

  const handleMessage = useCallback(
    (message: WSMessage) => {
      if (isDev) {
        if (debugPayloads) {
          console.log('[useStreaming] Received message:', message.type, message);
        } else {
          console.log('[useStreaming] Received message:', message.type);
        }
      }

      switch (message.type) {
        case 'progress':
          if ('progress' in message && message.progress !== undefined) {
            updateProgress(message.progress, message.message || '');
            // Add to activity log if there's a meaningful message
            if (message.message && message.message.trim()) {
              addActivityLog(message.message, message.progress, 'progress');
            }
          }
          break;

        case 'status':
          // Handle status messages - check if task is already completed
          if ('progress' in message && message.progress !== undefined) {
            updateProgress(message.progress, message.message || '');
            // Add initial status to activity log
            if (message.message && message.message.trim()) {
              addActivityLog(message.message, message.progress, 'info');
            }
          }
          // Check if the status indicates completion (for reconnection after task finished)
          if ('status' in message) {
            const taskStatus = (message as unknown as { status: string }).status;
            if (taskStatus === 'completed') {
              if (isDev) {
                console.log('[useStreaming] Task already completed (from status message)');
              }
              // Don't set finished here - wait for the complete message with result
            } else if (taskStatus === 'error') {
              if (isDev) {
                console.log('[useStreaming] Task already errored (from status message)');
              }
            } else if (taskStatus === 'waiting_for_input') {
              if (isDev) {
                console.log('[useStreaming] Task waiting for input');
              }
              // The interaction details will come in a separate interaction_required message
            }
          }
          break;

        case 'interaction_required':
          // User-in-Loop: workflow is requesting user input
          if (isDev) {
            console.log('[useStreaming] Interaction required:', message.interaction_type);
          }
          addActivityLog(`⏸️ Waiting for input: ${message.title}`, 0, 'info');
          setPendingInteraction({
            type: message.interaction_type,
            title: message.title,
            description: message.description,
            data: message.data,
            options: message.options,
            required: message.required,
          });
          break;

        case 'complete':
          if (isDev) {
            console.log('[useStreaming] Workflow complete!');
            if (debugPayloads) {
              console.log('[useStreaming] Result:', message.result);
            }
          }
          setStatus('completed');  // This will make isFinished = true
          setResult(message.result);
          clearInteraction(); // Clear any pending interaction
          // Update progress to 100% to mark all steps as complete
          updateProgress(100, 'Workflow completed successfully');
          addActivityLog('✅ Workflow completed successfully!', 100, 'success');
          break;

        case 'error':
          {
          const errorText = typeof message.error === 'string' ? message.error : '';
          // Handle "Task not found" - clear state and stop reconnecting
          if (
            message.code?.toUpperCase() === 'TASK_NOT_FOUND'
            || errorText.toLowerCase().includes('task not found')
          ) {
            if (isDev) {
              console.log('[useStreaming] Task not found, clearing persisted state...');
            }
            // Reset the entire workflow state (this also clears localStorage)
            useWorkflowStore.getState().reset();
          } else {
            // Real error - mark as error state
            setStatus('error');  // This will make isFinished = true
            setError(errorText || 'Workflow failed with an unknown error');
            clearInteraction(); // Clear any pending interaction
            addActivityLog(`❌ Error: ${errorText || 'Unknown error'}`, 0, 'error');
          }
          break;
          }

        case 'cancelled':
          setStatus('cancelled');
          clearInteraction();
          setCurrentFile(null);
          addActivityLog(`⏹️ ${message.reason || message.message || 'Workflow cancelled'}`, 0, 'warning');
          break;

        case 'code_chunk':
          if (message.content) {
            appendStreamedCode(message.content);
          }
          break;

        case 'file_start':
          if (message.filename) {
            setCurrentFile(message.filename);
          }
          break;

        case 'file_end':
          if (message.filename) {
            addGeneratedFile(message.filename);
            setCurrentFile(null);
          }
          break;

        case 'heartbeat':
          // Ignore heartbeat messages
          break;

        case 'log':
          // Some servers may emit log frames; treat them as informational activity.
          addActivityLog(message.message, 0, 'info');
          break;
      }
    },
    [
      isDev,
      debugPayloads,
      updateProgress,
      setStatus,
      setResult,
      setError,
      appendStreamedCode,
      setCurrentFile,
      addGeneratedFile,
      addActivityLog,
      setPendingInteraction,
      clearInteraction,
    ]
  );

  // Compute effective URL - null if finished to stop WebSocket
  const workflowUrl = taskId && !isFinished ? `/ws/workflow/${taskId}` : null;
  const codeStreamUrl = taskId && !isFinished ? `/ws/code-stream/${taskId}` : null;

  const workflowWs = useWebSocket(workflowUrl, {
    onMessage: handleMessage as (message: unknown) => void,
    reconnect: true,
  });

  const codeStreamWs = useWebSocket(codeStreamUrl, {
    onMessage: handleMessage as (message: unknown) => void,
    reconnect: true,
  });

  // Reset status to running only when taskId actually changes to a new value
  useEffect(() => {
    if (taskId && taskId !== prevTaskIdRef.current) {
      if (isDev) {
        console.log(
          '[useStreaming] taskId changed from',
          prevTaskIdRef.current,
          'to',
          taskId,
          '- resetting to running'
        );
      }
      prevTaskIdRef.current = taskId;
      setStatus('running');
    } else if (!taskId) {
      prevTaskIdRef.current = null;
    }
  }, [isDev, taskId, setStatus]);

  return {
    isConnected: workflowWs.isConnected || codeStreamWs.isConnected,
    isFinished,
    disconnect: () => {
      workflowWs.disconnect();
      codeStreamWs.disconnect();
    },
  };
}
