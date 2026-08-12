import { createApiCompetitionDataProvider } from './apiCompetitionDataProvider.js';
import { createDemoCompetitionDataProvider } from './demoCompetitionDataProvider.js';

export function createCompetitionDataProvider(mode, options = {}) {
  if (mode === 'demo') return createDemoCompetitionDataProvider(options);
  if (mode === 'live') return createApiCompetitionDataProvider(options);
  throw new Error(`Unsupported competition data mode: ${mode}`);
}

const viteEnv = typeof import.meta.env === 'object' ? import.meta.env : {};

export const competitionDataMode = viteEnv.VITE_COMPETITION_DATA_MODE || 'live';
export const competitionDataProvider = createCompetitionDataProvider(competitionDataMode);
