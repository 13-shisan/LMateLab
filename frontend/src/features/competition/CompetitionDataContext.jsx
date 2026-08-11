/* eslint-disable react-refresh/only-export-components -- Provider and hooks share one context module. */
import { createContext, useContext, useEffect, useMemo, useState } from 'react';

import { competitionDataProvider } from './data/competitionDataProvider.js';


const CompetitionDataContext = createContext(null);
const loadingResource = Object.freeze({ status: 'loading', data: null, error: null });


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


export function useCompetitionResource(loader) {
  const [resource, setResource] = useState(loadingResource);

  useEffect(() => {
    let active = true;

    async function loadResource() {
      await Promise.resolve();
      if (!active) return;
      setResource(loadingResource);

      try {
        const data = await loader();
        if (!active) return;
        setResource({
          status: data == null ? 'empty' : 'ready',
          data: data ?? null,
          error: null,
        });
      } catch (error) {
        if (!active) return;
        setResource({
          status: error?.code === 'forbidden' ? 'forbidden' : 'error',
          data: null,
          error,
        });
      }
    }

    loadResource();
    return () => {
      active = false;
    };
  }, [loader]);

  return resource;
}
