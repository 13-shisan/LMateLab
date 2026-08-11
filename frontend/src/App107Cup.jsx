import { lazy, Suspense } from 'react';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';

import AppShell from './components/AppShell';
import CenterLoadingOverlay from './components/CenterLoadingOverlay';
import { CompetitionDataProvider } from './features/competition/CompetitionDataContext';
import RequireAuth from './routes/RequireAuth';


const Login = lazy(() => import('./pages/Login'));
const Dashboard = lazy(() => import('./pages/Dashboard'));


function RouteFallback() {
  return (
    <div style={{ position: 'fixed', inset: 0 }}>
      <CenterLoadingOverlay defaultText="正在加载页面..." />
    </div>
  );
}


function ProtectedAppShell() {
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
          <Route path="/" element={<Navigate to="/login" replace />} />
          <Route path="/login" element={<Login />} />
          <Route element={<ProtectedAppShell />}>
            <Route path="/dashboard" element={<Dashboard />} />
          </Route>
          <Route path="*" element={<Navigate to="/dashboard" replace />} />
        </Routes>
      </Suspense>
    </BrowserRouter>
  );
}
