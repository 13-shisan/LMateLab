/* eslint-disable react-refresh/only-export-components -- Provider and hooks share one context module. */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from 'react';

import { competitionDataProvider } from './data/competitionDataProvider.js';


const CompetitionDataContext = createContext(null);
const loadingResource = Object.freeze({
  status: 'loading',
  data: null,
  error: null,
  refreshing: false,
  requestKey: null,
  refreshError: null,
});


export function CompetitionDataProvider({ children, provider = competitionDataProvider }) {
  const value = useMemo(() => ({
    provider,
    mode: provider.mode,
    readOnly: provider.readOnly,
  }), [provider]);

  return (
    <CompetitionDataContext.Provider value={value}>
      {children}
    </CompetitionDataContext.Provider>
  );
}


export function useCompetitionData() {
  const context = useContext(CompetitionDataContext);
  if (context === null) {
    throw new Error('useCompetitionData must be used inside CompetitionDataProvider');
  }
  return context;
}


export function beginCompetitionResourceLoad(
  resource,
  { preserveReady = false, requestKey = null } = {},
) {
  if (
    preserveReady
    && resource?.status === 'ready'
    && resource.requestKey === requestKey
  ) {
    return { ...resource, error: null, refreshing: true };
  }
  return { ...loadingResource, requestKey };
}


export function finishCompetitionResourceError(
  resource,
  error,
  { preserveReady = false, requestKey = null } = {},
) {
  if (
    preserveReady
    && resource?.status === 'ready'
    && resource.data !== null
    && resource.requestKey === requestKey
  ) {
    return {
      ...resource,
      error: null,
      refreshing: false,
      refreshError: 'refresh-failed',
    };
  }
  return {
    status: error?.code === 'forbidden' ? 'forbidden' : 'error',
    data: null,
    error,
    refreshing: false,
    requestKey,
    refreshError: null,
  };
}


export function useCompetitionResource(
  loader,
  { preserveReady = false, requestKey = null } = {},
) {
  const [resource, setResource] = useState(
    () => beginCompetitionResourceLoad(loadingResource, { requestKey }),
  );

  useEffect(() => {
    let active = true;

    async function loadResource() {
      if (!active) return;
      setResource((current) => beginCompetitionResourceLoad(current, {
        preserveReady,
        requestKey,
      }));

      try {
        const data = await loader();
        if (!active) return;
        setResource({
          status: data == null ? 'empty' : 'ready',
          data: data ?? null,
          error: null,
          refreshing: false,
          requestKey,
          refreshError: null,
        });
      } catch (error) {
        if (!active) return;
        setResource((current) => finishCompetitionResourceError(current, error, {
          preserveReady,
          requestKey,
        }));
      }
    }

    loadResource();
    return () => {
      active = false;
    };
  }, [loader, preserveReady, requestKey]);

  return resource;
}


export function useCompetitionPollingResource(
  loader,
  { enabled, intervalMs = 10000, requestKey = null } = {},
) {
  const [refreshKey, setRefreshKey] = useState(0);
  const refresh = useCallback(() => setRefreshKey((value) => value + 1), []);
  const resource = useCompetitionResource(
    useCallback(() => loader(refreshKey), [loader, refreshKey]),
    { preserveReady: true, requestKey },
  );
  const pollingEnabled = typeof enabled === 'function' ? enabled(resource.data) : enabled;

  useEffect(() => {
    if (!pollingEnabled || resource.refreshing) return undefined;
    const timer = globalThis.setTimeout(
      refresh,
      intervalMs,
    );
    return () => globalThis.clearTimeout(timer);
  }, [pollingEnabled, intervalMs, resource.refreshing, refresh]);

  return useMemo(() => ({ ...resource, refresh }), [resource, refresh]);
}
