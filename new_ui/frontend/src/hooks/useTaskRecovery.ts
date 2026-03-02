/**
 * Task Recovery Hook
 *
 * Handles automatic recovery of running tasks after page refresh.
 *
 * Flow:
 * 1. On mount, check if there's a persisted activeTaskId
 * 2. If yes, query the backend to verify task status
 * 3. If task is still running, reconnect WebSocket
 * 4. If task is completed/error, sync the final state
 * 5. If task not found, clear the persisted state
 */

import { useEffect, useCallback, useState } from 'react';
import axios from 'axios';
import { useWorkflowStore } from '../stores/workflowStore';
import { workflowsApi } from '../services/api';
import { PAPER_TO_CODE_STEPS, CHAT_PLANNING_STEPS } from '../types/workflow';
import { shallow } from 'zustand/shallow';

interface RecoveryState {
  isRecovering: boolean;
  recoveredTaskId: string | null;
  error: string | null;
}

function isTaskNotFoundError(error: unknown): boolean {
  if (!axios.isAxiosError(error)) {
    return false;
  }

  if (error.response?.status === 404) {
    return true;
  }

  const responseData = error.response?.data as Record<string, unknown> | undefined;
  const code = responseData?.code;
  if (typeof code === 'string' && code.toUpperCase() === 'TASK_NOT_FOUND') {
    return true;
  }

  const detail = responseData?.detail;
  if (typeof detail === 'string' && detail.toLowerCase().includes('task not found')) {
    return true;
  }

  return error.message.toLowerCase().includes('task not found');
}

export function useTaskRecovery() {
  const isDev = import.meta.env.DEV;

  const {
    activeTaskId,
    workflowType,
    status,
    setStatus,
    setSteps,
    updateProgress,
    setResult,
    setError,
    setNeedsRecovery,
    reset,
  } = useWorkflowStore(
    (s) => ({
      activeTaskId: s.activeTaskId,
      workflowType: s.workflowType,
      status: s.status,
      setStatus: s.setStatus,
      setSteps: s.setSteps,
      updateProgress: s.updateProgress,
      setResult: s.setResult,
      setError: s.setError,
      setNeedsRecovery: s.setNeedsRecovery,
      reset: s.reset,
    }),
    shallow
  );

  const [recoveryState, setRecoveryState] = useState<RecoveryState>({
    isRecovering: false,
    recoveredTaskId: null,
    error: null,
  });

  const recoverTask = useCallback(async () => {
    // Only recover if there's a persisted task and it was running
    if (!activeTaskId || status === 'idle' || status === 'completed' || status === 'error') {
      return;
    }

    if (isDev) {
      console.log('[TaskRecovery] Attempting to recover task:', activeTaskId);
    }
    setRecoveryState({ isRecovering: true, recoveredTaskId: null, error: null });

    try {
      // Query backend for task status
      const taskStatus = await workflowsApi.getStatus(activeTaskId);
      const backendStatus = taskStatus.status;

      const restoreWorkflowSteps = () => {
        if (workflowType === 'paper-to-code') {
          setSteps(PAPER_TO_CODE_STEPS);
        } else if (workflowType === 'chat-planning') {
          setSteps(CHAT_PLANNING_STEPS);
        }
      };

      if (isDev) {
        console.log('[TaskRecovery] Task status from backend:', taskStatus);
      }

      if (backendStatus === 'running') {
        // Task is still running - restore steps and let WebSocket reconnect
        if (isDev) {
          console.log('[TaskRecovery] Task still running, reconnecting...');
        }

        // Restore steps based on workflow type
        restoreWorkflowSteps();

        // Update progress from backend
        updateProgress(taskStatus.progress, taskStatus.message);
        setStatus('running');
        setNeedsRecovery(false);

        setRecoveryState({
          isRecovering: false,
          recoveredTaskId: activeTaskId,
          error: null,
        });

      } else if (backendStatus === 'pending') {
        // Task is queued/initializing - keep current workflow state and continue listening
        if (isDev) {
          console.log('[TaskRecovery] Task pending, preserving recovery state...');
        }

        // Restore steps based on workflow type
        restoreWorkflowSteps();

        updateProgress(taskStatus.progress, taskStatus.message || 'Task is pending');
        // Keep frontend in a recoverable active state while backend transitions to running
        setStatus('running');
        setNeedsRecovery(false);

        setRecoveryState({
          isRecovering: false,
          recoveredTaskId: activeTaskId,
          error: null,
        });

      } else if (backendStatus === 'waiting_for_input') {
        // Task is paused for user input - keep active state and wait for interaction payload via WebSocket
        if (isDev) {
          console.log('[TaskRecovery] Task waiting for input, preserving active state...');
        }

        restoreWorkflowSteps();
        updateProgress(
          taskStatus.progress,
          taskStatus.message || 'Task is waiting for your input'
        );
        setStatus('running');
        setNeedsRecovery(false);

        setRecoveryState({
          isRecovering: false,
          recoveredTaskId: activeTaskId,
          error: null,
        });

      } else if (backendStatus === 'completed') {
        // Task completed while we were away
        if (isDev) {
          console.log('[TaskRecovery] Task completed, syncing final state...');
        }

        restoreWorkflowSteps();

        updateProgress(100, 'Completed');
        setStatus('completed');
        setResult(taskStatus.result || null);
        setNeedsRecovery(false);

        setRecoveryState({
          isRecovering: false,
          recoveredTaskId: activeTaskId,
          error: null,
        });

      } else if (backendStatus === 'error') {
        // Task errored while we were away
        if (isDev) {
          console.log('[TaskRecovery] Task errored, syncing error state...');
        }

        setStatus('error');
        setError(taskStatus.error || 'Unknown error');
        setNeedsRecovery(false);

        setRecoveryState({
          isRecovering: false,
          recoveredTaskId: activeTaskId,
          error: taskStatus.error || null,
        });

      } else if (backendStatus === 'cancelled') {
        if (isDev) {
          console.log('[TaskRecovery] Task cancelled, clearing persisted state...');
        }
        reset();
        setRecoveryState({
          isRecovering: false,
          recoveredTaskId: null,
          error: null,
        });

      } else {
        // Unknown status - keep state to avoid destructive resets on transient backend changes
        if (isDev) {
          console.warn('[TaskRecovery] Unknown task status, keeping current state:', backendStatus);
        }
        setNeedsRecovery(true);
        setRecoveryState({
          isRecovering: false,
          recoveredTaskId: null,
          error: `Unknown task status: ${backendStatus}`,
        });
      }

    } catch (error) {
      // Task not found or API error
      console.error('[TaskRecovery] Failed to recover task:', error);

      if (isTaskNotFoundError(error)) {
        // 404/task-not-found means task is gone: clear stale persisted state
        if (isDev) {
          console.log('[TaskRecovery] Task not recoverable, clearing state...');
        }
        reset();
        setNeedsRecovery(false);
        setRecoveryState({
          isRecovering: false,
          recoveredTaskId: null,
          error: null,
        });
        return;
      }

      // Preserve active state on transient API errors so pending/running tasks can continue recovering.
      setNeedsRecovery(true);
      setRecoveryState({
        isRecovering: false,
        recoveredTaskId: null,
        error: 'Recovery check failed. Retrying on reconnect.',
      });
    }
  }, [
    isDev,
    activeTaskId,
    workflowType,
    status,
    setStatus,
    setSteps,
    updateProgress,
    setResult,
    setError,
    setNeedsRecovery,
    reset,
  ]);

  // Run recovery on mount
  useEffect(() => {
    // Only run once on initial mount if there's a persisted running task
    if (activeTaskId && (status === 'running' || (status as string) === 'pending')) {
      setNeedsRecovery(true);
      recoverTask();
    }
  }, []); // Empty deps - only run on mount

  return {
    ...recoveryState,
    recoverTask,
  };
}
