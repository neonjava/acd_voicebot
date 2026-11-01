import React from 'react';
import { BackendError, NetworkError } from '../services/sessionClient';
import { MalformedResponseError } from '../utils/validation';

export interface AppErrorState {
  type: 'permission' | 'malformed' | 'backend' | 'network' | 'generic';
  title: string;
  message: string;
  code?: string;
  correlationId?: string;
  retryable?: boolean;
}

interface StatusAlertProps {
  statusMessage: string | null;
  error: AppErrorState | null;
  onDismissError?: () => void;
}

export const StatusAlert: React.FC<StatusAlertProps> = ({
  statusMessage,
  error,
  onDismissError,
}) => {
  return (
    <div className="status-announcements" style={{ marginBottom: '16px' }}>
      {/* Live region for status updates */}
      <div
        role="status"
        aria-live="polite"
        className="live-status-message"
        style={{
          display: statusMessage ? 'block' : 'none',
          padding: '8px 12px',
          backgroundColor: '#e7f5ff',
          color: '#1864ab',
          borderRadius: '4px',
          marginBottom: error ? '10px' : '0',
          fontSize: '0.9rem',
          fontWeight: 500,
        }}
      >
        {statusMessage}
      </div>

      {/* Live region for errors */}
      {error && (
        <div
          role="alert"
          aria-live="assertive"
          className="live-error-alert"
          data-testid="error-alert"
          style={{
            padding: '12px 16px',
            backgroundColor: '#f8d7da',
            border: '1px solid #f5c6cb',
            color: '#721c24',
            borderRadius: '6px',
            fontSize: '0.9rem',
          }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
            <h4 style={{ margin: '0 0 6px 0', fontSize: '1rem', fontWeight: 600 }}>
              {error.title}
            </h4>
            {onDismissError && (
              <button
                type="button"
                onClick={onDismissError}
                aria-label="Dismiss error"
                style={{
                  background: 'none',
                  border: 'none',
                  color: '#721c24',
                  cursor: 'pointer',
                  fontWeight: 'bold',
                  fontSize: '1rem',
                }}
              >
                &times;
              </button>
            )}
          </div>
          <p style={{ margin: '0 0 6px 0' }}>{error.message}</p>
          {(error.code || error.correlationId || error.retryable !== undefined) && (
            <div
              style={{
                fontSize: '0.8rem',
                color: '#491217',
                marginTop: '6px',
                fontFamily: 'monospace',
                display: 'flex',
                flexWrap: 'wrap',
                gap: '12px',
              }}
            >
              {error.code && <span>Code: {error.code}</span>}
              {error.correlationId && <span>Correlation ID: {error.correlationId}</span>}
              {error.retryable !== undefined && (
                <span>Retryable: {error.retryable ? 'Yes' : 'No'}</span>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export function formatErrorToState(err: unknown): AppErrorState {
  if (err instanceof BackendError) {
    return {
      type: 'backend',
      title: 'Backend Error',
      message: err.message,
      code: err.code,
      correlationId: err.correlationId,
      retryable: err.retryable,
    };
  }
  if (err instanceof MalformedResponseError) {
    return {
      type: 'malformed',
      title: 'Malformed Response Error',
      message: err.message,
      code: 'FRONTEND_MALFORMED_RESPONSE',
    };
  }
  if (err instanceof NetworkError) {
    return {
      type: 'network',
      title: 'Network Connection Failure',
      message: err.message,
      code: err.status ? `HTTP_${err.status}` : 'NETWORK_OFFLINE',
      retryable: true,
    };
  }
  if (err instanceof Error) {
    return {
      type: 'generic',
      title: 'Operation Failed',
      message: err.message,
    };
  }
  return {
    type: 'generic',
    title: 'Unexpected Error',
    message: String(err),
  };
}
