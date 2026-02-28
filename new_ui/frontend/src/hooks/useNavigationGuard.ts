/**
 * Navigation Guard Hook
 *
 * Prevents accidental navigation away from a page when a task is running.
 * - Shows browser warning on refresh/close (beforeunload)
 * - Shows confirmation dialog on in-app navigation
 */

import { useCallback, useEffect } from 'react';
import { useBlocker } from 'react-router-dom';
import { shallow } from 'zustand/shallow';
import { useWorkflowStore } from '../stores/workflowStore';

export function useNavigationGuard() {
  const { status, isWaitingForInput } = useWorkflowStore(
    (s) => ({
      status: s.status,
      isWaitingForInput: s.isWaitingForInput,
    }),
    shallow
  );
  const shouldBlock = status === 'running' || isWaitingForInput === true;
  const blocker = useBlocker(shouldBlock);

  // Handle browser beforeunload event (refresh, close tab, close browser)
  useEffect(() => {
    const handleBeforeUnload = (e: BeforeUnloadEvent) => {
      if (shouldBlock) {
        e.preventDefault();
        // Chrome requires returnValue to be set
        e.returnValue = 'A task is still running. Are you sure you want to leave?';
        return e.returnValue;
      }
    };

    window.addEventListener('beforeunload', handleBeforeUnload);
    return () => window.removeEventListener('beforeunload', handleBeforeUnload);
  }, [shouldBlock]);

  // Confirm navigation (user clicked "Leave" in dialog)
  const confirmNavigation = useCallback(() => {
    if (blocker.state === 'blocked') {
      blocker.proceed();
    }
  }, [blocker]);

  // Cancel navigation (user clicked "Stay" in dialog)
  const cancelNavigation = useCallback(() => {
    if (blocker.state === 'blocked') {
      blocker.reset();
    }
  }, [blocker]);

  return {
    isBlocking: shouldBlock,
    showConfirmDialog: blocker.state === 'blocked',
    confirmNavigation,
    cancelNavigation,
  };
}
