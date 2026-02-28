import type { RefObject } from 'react';
import { AnimatePresence, m } from 'framer-motion';
import { Bot, MessageSquare, User } from 'lucide-react';
import type { PendingInteraction } from '../../stores/workflowStore';
import type { Message } from '../../types/common';
import InlineChatInteraction from '../interaction/InlineChatInteraction';

interface ChatTranscriptProps {
  containerRef: RefObject<HTMLDivElement>;
  conversationHistory: Message[];
  pendingInteraction: PendingInteraction | null;
  activeTaskId: string | null;
}

export default function ChatTranscript({
  containerRef,
  conversationHistory,
  pendingInteraction,
  activeTaskId,
}: ChatTranscriptProps) {
  return (
    <div
      ref={containerRef}
      className="flex-1 overflow-y-auto p-4 space-y-4"
    >
      {conversationHistory.length === 0 && !pendingInteraction ? (
        <div className="h-full flex items-center justify-center text-center text-gray-400">
          <div>
            <MessageSquare className="h-12 w-12 mx-auto mb-3 opacity-50" />
            <p className="text-sm">
              Describe your project requirements to get started
            </p>
          </div>
        </div>
      ) : (
        <>
          {conversationHistory.map((msg) => (
            <m.div
              key={msg.id}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              className={`flex items-start space-x-3 ${
                msg.role === 'user' ? 'flex-row-reverse space-x-reverse' : ''
              }`}
            >
              <div
                className={`flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center ${
                  msg.role === 'user' ? 'bg-primary-100' : 'bg-gray-100'
                }`}
              >
                {msg.role === 'user' ? (
                  <User className="h-4 w-4 text-primary-600" />
                ) : (
                  <Bot className="h-4 w-4 text-gray-600" />
                )}
              </div>
              <div
                className={`max-w-[80%] px-4 py-2 rounded-2xl ${
                  msg.role === 'user'
                    ? 'bg-primary-500 text-white'
                    : 'bg-gray-100 text-gray-900'
                }`}
              >
                <p className="text-sm whitespace-pre-wrap">{msg.content}</p>
              </div>
            </m.div>
          ))}

          {/* Inline Interaction - displayed in chat flow */}
          <AnimatePresence>
            {pendingInteraction && activeTaskId ? (
              <InlineChatInteraction
                taskId={activeTaskId}
                interaction={pendingInteraction}
              />
            ) : null}
          </AnimatePresence>
        </>
      )}
    </div>
  );
}

