import { m } from 'framer-motion';
import { CheckCircle, FolderOpen, XCircle } from 'lucide-react';
import { Card } from '../common';

type Variant = 'success' | 'error';

interface WorkflowOutcomeCardProps {
  variant: Variant;
  title: string;
  message: string;
  codeDirectory?: string | null;
}

export default function WorkflowOutcomeCard({
  variant,
  title,
  message,
  codeDirectory,
}: WorkflowOutcomeCardProps) {
  const isSuccess = variant === 'success';
  const Icon = isSuccess ? CheckCircle : XCircle;

  return (
    <m.div
      initial={{ opacity: 0, scale: 0.95 }}
      animate={{ opacity: 1, scale: 1 }}
    >
      <Card className={isSuccess ? 'border-green-200 bg-green-50' : 'border-red-200 bg-red-50'}>
        <div className="flex items-start space-x-3">
          <Icon
            className={`h-6 w-6 flex-shrink-0 ${isSuccess ? 'text-green-500' : 'text-red-500'}`}
          />
          <div className="flex-1">
            <h3 className={`font-medium ${isSuccess ? 'text-green-900' : 'text-red-900'}`}>
              {title}
            </h3>
            <p className={`text-sm mt-1 ${isSuccess ? 'text-green-700' : 'text-red-700'}`}>
              {message}
            </p>
            {isSuccess && codeDirectory ? (
              <div className="mt-3 flex items-center text-sm text-green-600">
                <FolderOpen className="h-4 w-4 mr-2" />
                <span className="font-mono text-xs">{codeDirectory}</span>
              </div>
            ) : null}
          </div>
        </div>
      </Card>
    </m.div>
  );
}

