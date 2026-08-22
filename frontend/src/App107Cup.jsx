import { lazy, Suspense } from 'react';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';

import AppShell from './components/AppShell';
import CenterLoadingOverlay from './components/CenterLoadingOverlay';
import { CompetitionDataProvider } from './features/competition/CompetitionDataContext';
import RequireAuth from './routes/RequireAuth';


const CompetitionHome = lazy(() => import('./pages/competition/CompetitionHome'));
const Login = lazy(() => import('./pages/Login'));
const CompetitionDashboard = lazy(() => import('./pages/CompetitionDashboard'));
const CompetitionNewCalculation = lazy(() => import('./pages/competition/CompetitionNewCalculation'));
const CompetitionWorkflows = lazy(() => import('./pages/competition/CompetitionWorkflows'));
const CompetitionWorkflowDetail = lazy(() => import('./pages/competition/CompetitionWorkflowDetail'));
const CompetitionResults = lazy(() => import('./pages/competition/CompetitionResults'));
const CompetitionResultDetail = lazy(() => import('./pages/competition/CompetitionResultDetail'));
const CompetitionVaspDatabase = lazy(() => import('./pages/competition/CompetitionVaspDatabase'));


function RouteFallback() {
  return (
    <div style={{ position: 'fixed', inset: 0 }}>
      <CenterLoadingOverlay defaultText="正在加载页面..." />
    </div>
  );
}


function ProtectedCompetitionShell() {
  return (
    <RequireAuth>
      <CompetitionDataProvider>
        <AppShell />
      </CompetitionDataProvider>
    </RequireAuth>
  );
}


export default function App107Cup() {
  return (
    <BrowserRouter>
      <Suspense fallback={<RouteFallback />}>
        <Routes>
          <Route path="/" element={<CompetitionHome />} />
          <Route path="/login" element={<Login />} />
          <Route element={<ProtectedCompetitionShell />}>
            <Route path="/dashboard" element={<CompetitionDashboard />} />
            <Route path="/dashboard/calculations/new" element={<CompetitionNewCalculation />} />
            <Route path="/dashboard/workflows" element={<CompetitionWorkflows />} />
            <Route path="/dashboard/workflows/:workflowId" element={<CompetitionWorkflowDetail />} />
            <Route path="/dashboard/results" element={<CompetitionResults />} />
            <Route path="/dashboard/results/:workflowId" element={<CompetitionResultDetail />} />
            <Route path="/dashboard/database/vasp" element={<CompetitionVaspDatabase />} />
          </Route>
          <Route path="*" element={<Navigate to="/dashboard" replace />} />
        </Routes>
      </Suspense>
    </BrowserRouter>
  );
}
