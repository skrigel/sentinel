import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';

interface IssueNotificationProps {
  agentName: string;
  issue: string;
  severity: 'warning' | 'critical';
  onDismiss: () => void;
}

export function IssueNotification({ agentName, issue, severity, onDismiss }: IssueNotificationProps) {
  const [isVisible, setIsVisible] = useState(false);

  useEffect(() => {
    setTimeout(() => setIsVisible(true), 100);
  }, []);

  const handleDismiss = () => {
    setIsVisible(false);
    setTimeout(onDismiss, 300);
  };

  return (
    <div
      className={`fixed top-6 right-6 w-96 bg-white border-2 rounded-lg shadow-lg transition-all duration-300 z-50 ${
        severity === 'critical' ? 'border-red-300' : 'border-amber-300'
      } ${isVisible ? 'translate-x-0 opacity-100' : 'translate-x-8 opacity-0'}`}
    >
      <div className="p-5">
        {/* Header */}
        <div className="flex items-start justify-between gap-3 mb-3">
          <div className="flex items-center gap-2">
            <div className={`w-2 h-2 rounded-full ${
              severity === 'critical' ? 'bg-red-500' : 'bg-amber-500'
            } animate-pulse`} />
            <div className="text-sm font-medium text-gray-900">Issue Detected</div>
          </div>
          <button
            onClick={handleDismiss}
            className="text-gray-400 hover:text-gray-600 transition-colors"
          >
            <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
              <path fillRule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clipRule="evenodd" />
            </svg>
          </button>
        </div>

        {/* Content */}
        <div className="space-y-2 mb-4">
          <div className="flex items-center gap-2">
            <div className="text-sm font-medium text-gray-900">{agentName}</div>
            <div className={`text-xs px-2 py-0.5 rounded ${
              severity === 'critical'
                ? 'bg-red-50 text-red-700'
                : 'bg-amber-50 text-amber-700'
            }`}>
              {severity}
            </div>
          </div>
          <div className="text-sm text-gray-600">{issue}</div>
        </div>

        {/* Actions */}
        <div className="flex gap-2">
          <Link
            to="/sentinel"
            className="flex-1 px-3 py-2 bg-gray-900 text-white text-sm font-medium rounded hover:bg-gray-800 transition-colors text-center"
          >
            View Details
          </Link>
          <button
            onClick={handleDismiss}
            className="px-3 py-2 bg-gray-100 text-gray-700 text-sm font-medium rounded hover:bg-gray-200 transition-colors"
          >
            Dismiss
          </button>
        </div>
      </div>
    </div>
  );
}
