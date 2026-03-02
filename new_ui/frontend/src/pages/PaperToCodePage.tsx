import { useState, useEffect } from 'react';
import { AnimatePresence, m } from 'framer-motion';
import { Card, Button } from '../components/common';
import { FileUploader, UrlInput } from '../components/input';
import { ProgressTracker, ActivityLogViewer } from '../components/streaming';
import { FileTree, WorkflowOutcomeCard } from '../components/results';
import { InteractionPanel } from '../components/interaction';
import { useWorkflowStore } from '../stores/workflowStore';
import { useStreaming } from '../hooks/useStreaming';
import { workflowsApi } from '../services/api';
import { toast } from '../components/common/Toaster';
import { PAPER_TO_CODE_STEPS } from '../types/workflow';
import { StopCircle } from 'lucide-react';
import { ConfirmDialog } from '../components/common/ConfirmDialog';
import { shallow } from 'zustand/shallow';

type InputMethod = 'file' | 'url';

export default function PaperToCodePage() {
  const [local, setLocal] = useState({
    inputMethod: 'file' as InputMethod,
    uploadedFilePath: null as string | null,
    enableIndexing: false,
    showCancelDialog: false,
    isCancelling: false,
  });
  const { inputMethod, uploadedFilePath, enableIndexing, showCancelDialog, isCancelling } = local;

  const {
    activeTaskId,
    status,
    progress,
    message,
    steps,
    generatedFiles,
    activityLogs,
    pendingInteraction,
    isWaitingForInput,
    result,
    error,
    setActiveTask,
    setSteps,
    setStatus,
    reset,
  } = useWorkflowStore(
    (s) => ({
      activeTaskId: s.activeTaskId,
      status: s.status,
      progress: s.progress,
      message: s.message,
      steps: s.steps,
      generatedFiles: s.generatedFiles,
      activityLogs: s.activityLogs,
      pendingInteraction: s.pendingInteraction,
      isWaitingForInput: s.isWaitingForInput,
      result: s.result,
      error: s.error,
      setActiveTask: s.setActiveTask,
      setSteps: s.setSteps,
      setStatus: s.setStatus,
      reset: s.reset,
    }),
    shallow
  );

  useStreaming(activeTaskId);

  // Show toast when workflow completes
  useEffect(() => {
    if (status === 'completed' && result) {
      toast.success('Paper processing complete!', 'Code has been generated successfully.');
    } else if (status === 'error' && error) {
      toast.error('Processing failed', error);
    }
  }, [status, error, result]);

  // Handle task cancellation
  const handleCancelTask = async () => {
    if (!activeTaskId) return;

    setLocal((s) => ({ ...s, isCancelling: true }));
    try {
      await workflowsApi.cancel(activeTaskId);
      setStatus('idle');
      reset();
      toast.info('Task cancelled', 'The workflow has been stopped.');
    } catch (err) {
      toast.error('Cancel failed', 'Could not cancel the task.');
      console.error('Cancel error:', err);
    } finally {
      setLocal((s) => ({ ...s, isCancelling: false, showCancelDialog: false }));
    }
  };

  const handleStart = async (inputSource: string, inputType: 'file' | 'url') => {
    try {
      reset();
      setSteps(PAPER_TO_CODE_STEPS);

      const response = await workflowsApi.startPaperToCode(
        inputSource,
        inputType,
        enableIndexing
      );

      setActiveTask(response.task_id, 'paper-to-code');
      toast.info('Workflow started', 'Processing your paper...');
    } catch (error) {
      toast.error('Failed to start workflow', 'Please try again');
      console.error('Start error:', error);
    }
  };

  const handleFileUploaded = (_fileId: string, path: string) => {
    setLocal((s) => ({ ...s, uploadedFilePath: path }));
  };

  const handleFileRemoved = () => {
    setLocal((s) => ({ ...s, uploadedFilePath: null }));
  };

  const handleUrlSubmit = (url: string) => {
    handleStart(url, 'url');
  };

  const handleStartWithFile = () => {
    if (uploadedFilePath) {
      handleStart(uploadedFilePath, 'file');
    }
  };

  const isRunning = status === 'running';
  const codeDirectory =
    result?.repo_result &&
    typeof result.repo_result === 'object' &&
    result.repo_result !== null &&
    'code_directory' in (result.repo_result as Record<string, unknown>)
      ? String((result.repo_result as Record<string, unknown>).code_directory)
      : null;

  return (
    <div className="space-y-6">
      {/* Header */}
      <m.div
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
      >
        <h1 className="text-2xl font-bold text-gray-900">Paper to Code</h1>
        <p className="text-gray-500 mt-1">
          Upload a research paper and convert it to a working implementation
        </p>
      </m.div>

      <div className="grid gap-6 lg:grid-cols-2">
        {/* Left Column - Input */}
        <div className="space-y-6">
          <Card>
            <h3 className="font-semibold text-gray-900 mb-4">Input Source</h3>

            {/* Input Method Tabs */}
            <div className="flex space-x-2 mb-4">
              <button
                onClick={() => setLocal((s) => ({ ...s, inputMethod: 'file' }))}
                className={`flex-1 px-4 py-2 text-sm font-medium rounded-lg transition-colors ${
                  inputMethod === 'file'
                    ? 'bg-primary-50 text-primary-600'
                    : 'text-gray-600 hover:bg-gray-50'
                }`}
              >
                Upload PDF
              </button>
              <button
                onClick={() => setLocal((s) => ({ ...s, inputMethod: 'url' }))}
                className={`flex-1 px-4 py-2 text-sm font-medium rounded-lg transition-colors ${
                  inputMethod === 'url'
                    ? 'bg-primary-50 text-primary-600'
                    : 'text-gray-600 hover:bg-gray-50'
                }`}
              >
                URL Link
              </button>
            </div>

            {/* Input Components */}
            {inputMethod === 'file' ? (
              <div className="space-y-4">
                <FileUploader
                  onFileUploaded={handleFileUploaded}
                  onFileRemoved={handleFileRemoved}
                  disabled={isRunning}
                />
                {uploadedFilePath && !isRunning && (
                  <Button
                    onClick={handleStartWithFile}
                    isLoading={isRunning}
                    className="w-full"
                  >
                    Start Processing
                  </Button>
                )}
              </div>
            ) : (
              <UrlInput onSubmit={handleUrlSubmit} isLoading={isRunning} disabled={isRunning} />
            )}

            {/* Cancel Button */}
            {isRunning && (
              <div className="mt-4">
                <button
                  onClick={() => setLocal((s) => ({ ...s, showCancelDialog: true }))}
                  disabled={isCancelling}
                  className="w-full flex items-center justify-center space-x-2 px-4 py-2 text-sm font-medium text-red-600 bg-red-50 border border-red-200 rounded-lg hover:bg-red-100 transition-colors disabled:opacity-50"
                >
                  <StopCircle className="h-4 w-4" />
                  <span>Cancel Task</span>
                </button>
              </div>
            )}

            {/* Options */}
            <div className="mt-6 pt-4 border-t border-gray-100">
              <label className="flex items-center space-x-3 cursor-pointer">
                <input
                  type="checkbox"
                  checked={enableIndexing}
                  onChange={(e) => setLocal((s) => ({ ...s, enableIndexing: e.target.checked }))}
                  className="w-4 h-4 text-primary-600 rounded focus:ring-primary-500"
                />
                <span className="text-sm text-gray-700">
                  Enable code indexing
                </span>
              </label>
              <p className="text-xs text-gray-400 mt-1 ml-7">
                Improves code quality but takes longer
              </p>
            </div>
          </Card>
        </div>

        {/* Right Column - Progress & Results */}
        <div className="space-y-6">
          {/* Progress */}
          {status !== 'idle' && (
            <Card>
              <ProgressTracker steps={steps} currentProgress={progress} />
            </Card>
          )}

          {/* User-in-Loop Interaction Panel */}
          <AnimatePresence>
            {pendingInteraction && activeTaskId && (
              <InteractionPanel
                taskId={activeTaskId}
                interaction={pendingInteraction}
              />
            )}
          </AnimatePresence>

          {/* Activity Log */}
          <ActivityLogViewer
            logs={activityLogs}
            isRunning={isRunning && !isWaitingForInput}
            currentMessage={isWaitingForInput ? 'Waiting for your input...' : message}
          />

          {/* Generated Files */}
          {generatedFiles.length > 0 && (
            <FileTree files={generatedFiles} />
          )}

          {/* Completion Status */}
          {status === 'completed' && result && (
            <WorkflowOutcomeCard
              variant="success"
              title="Code Generation Complete!"
              message="Your code has been successfully generated from the paper."
              codeDirectory={codeDirectory}
            />
          )}

          {/* Error Status */}
          {status === 'error' && error && (
            <WorkflowOutcomeCard
              variant="error"
              title="Processing Failed"
              message={error}
            />
          )}
        </div>
      </div>

      {/* Cancel Confirmation Dialog */}
      <ConfirmDialog
        isOpen={showCancelDialog}
        title="Cancel Task?"
        message="Are you sure you want to cancel this task? Any progress will be lost and you'll need to start over."
        confirmLabel="Yes, Cancel"
        cancelLabel="Keep Running"
        variant="danger"
        onConfirm={handleCancelTask}
        onCancel={() => setLocal((s) => ({ ...s, showCancelDialog: false }))}
      />
    </div>
  );
}
