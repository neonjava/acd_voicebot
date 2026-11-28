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
  isLoading?: boolean;
  isOffline?: boolean;
}

export const StatusAlert: React.FC<StatusAlertProps> = ({
  statusMessage,
  error,
  onDismissError,
  isLoading = false,
  isOffline = false,
}) => {
  return (
    <div className="status-announcements">
      {isOffline && (
        <div role="status" aria-live="polite" data-testid="offline-indicator" className="note note-warn">
          <strong>Network Offline:</strong> Your browser reports no internet connectivity. HTTP session
          requests will fail until connection is restored.
        </div>
      )}

      {isLoading && (
        <div role="status" aria-live="polite" data-testid="loading-indicator" className="note note-muted">
          <span className="spinner" aria-hidden="true" />
          <span>Connecting to session and awaiting mock stream events...</span>
        </div>
      )}

      <div
        role="status"
        aria-live="polite"
        className={`live-status-message${statusMessage ? '' : ' is-empty'}`}
        data-testid="live-status-message"
      >
        {statusMessage}
      </div>

      {error && (
        <div role="alert" aria-live="assertive" className="live-error-alert" data-testid="error-alert">
          <div className="err-head">
            <h4>{error.title}</h4>
            {onDismissError && (
              <button type="button" className="err-dismiss" onClick={onDismissError} aria-label="Dismiss error">
                &times;
              </button>
            )}
          </div>
          <p>{error.message}</p>
          {(error.code || error.correlationId || error.retryable !== undefined) && (
            <div className="err-meta">
              {error.code && <span>Code: {error.code}</span>}
              {error.correlationId && <span>Correlation ID: {error.correlationId}</span>}
              {error.retryable !== undefined && <span>Retryable: {error.retryable ? 'Yes' : 'No'}</span>}
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
      title: err.code === 'DEPENDENCY_UNAVAILABLE' ? 'Upstream Dependency Unavailable' : 'Backend Error',
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
      title: err.isOffline ? 'Offline Error' : 'Network Connection Failure',
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
