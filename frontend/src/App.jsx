import { lazy, Suspense } from 'react';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';

import AppShell from './components/AppShell';
import CenterLoadingOverlay from './components/CenterLoadingOverlay';
import RequireAuth from './routes/RequireAuth';

const Home = lazy(() => import('./pages/Home'));
const Login = lazy(() => import('./pages/Login'));
const Register = lazy(() => import('./pages/Register'));
const ForgotPassword = lazy(() => import('./pages/ForgotPassword'));
const Dashboard = lazy(() => import('./pages/Dashboard'));
const AcademicReports = lazy(() => import('./pages/AcademicReports'));
const Changelog = lazy(() => import('./pages/Changelog'));
const Issues = lazy(() => import('./pages/issues'));
const NotesJournal = lazy(() => import('./pages/notes/Journal'));
const TasksEntry = lazy(() => import('./pages/notes/TasksEntry'));
const TasksAll = lazy(() => import('./pages/notes/TasksAll'));
const TasksVasp = lazy(() => import('./pages/notes/TasksVasp'));
const TasksQe = lazy(() => import('./pages/notes/TasksQe'));
const TasksGaussian = lazy(() => import('./pages/notes/TasksGaussian'));
const TasksDeepmd = lazy(() => import('./pages/notes/TasksDeepmd'));
const TasksLasp = lazy(() => import('./pages/notes/TasksLasp'));
const TasksCp2k = lazy(() => import('./pages/notes/TasksCp2k'));
const PapersDaily = lazy(() => import('./pages/papers/daily'));
const PapersSubscription = lazy(() => import('./pages/papers/subscription'));
const PapersLibrary = lazy(() => import('./pages/papers/library'));
const GroupDatabase = lazy(() => import('./pages/db/GroupDatabase'));
const PersonalDatabaseEntry = lazy(() => import('./pages/db/PersonalDatabaseEntry'));
const PersonalVaspDatabase = lazy(() => import('./pages/db/PersonalVaspDatabase'));
const PersonalQeEpwDatabase = lazy(() => import('./pages/db/PersonalQeEpwDatabase'));
const VaspTaskDetail = lazy(() => import('./pages/db/VaspTaskDetail'));
const QeEpwTaskDetail = lazy(() => import('./pages/db/QeEpwTaskDetail'));
const ServerMonitorEntry = lazy(() => import('./pages/server_monitor/ServerMonitorEntry'));
const ServerMonitorUsersOverview = lazy(() => import('./pages/server_monitor/ServerMonitorUsersOverview'));
const ServerMonitorPage = lazy(() => import('./pages/server_monitor/ServerMonitorPage'));
const AgentEntry = lazy(() => import('./pages/agents/AgentEntry'));
const GeneralChatAgent = lazy(() => import('./pages/agents/GeneralChatAgent'));
const PlatformGuideAgent = lazy(() => import('./pages/agents/PlatformGuideAgent'));
const ComingSoon = lazy(() => import('./pages/ComingSoon'));

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
      <AppShell />
    </RequireAuth>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <Suspense fallback={<RouteFallback />}>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/login" element={<Login />} />
          <Route path="/register" element={<Register />} />
          <Route path="/forgot-password" element={<ForgotPassword />} />

          <Route element={<ProtectedAppShell />}>
            <Route path="/dashboard" element={<Dashboard />} />
            <Route path="/dashboard/academic-reports" element={<AcademicReports />} />
            <Route path="/dashboard/changelog" element={<Changelog />} />
            <Route path="/dashboard/issues" element={<Issues />} />
            <Route path="/dashboard/issues/:id" element={<Issues />} />
            <Route path="/dashboard/notes/journal" element={<NotesJournal />} />
            <Route path="/dashboard/notes/tasksentry" element={<TasksEntry />} />
            <Route path="/dashboard/notes/tasksall" element={<TasksAll />} />
            <Route path="/dashboard/notes/tasksvasp" element={<TasksVasp />} />
            <Route path="/dashboard/notes/tasksqe" element={<TasksQe />} />
            <Route path="/dashboard/notes/tasksgaussian" element={<TasksGaussian />} />
            <Route path="/dashboard/notes/tasksdeepmd" element={<TasksDeepmd />} />
            <Route path="/dashboard/notes/taskslasp" element={<TasksLasp />} />
            <Route path="/dashboard/notes/taskscp2k" element={<TasksCp2k />} />
            <Route path="/dashboard/papers/daily" element={<PapersDaily />} />
            <Route path="/dashboard/papers/subscription" element={<PapersSubscription />} />
            <Route path="/dashboard/papers/library" element={<PapersLibrary />} />
            <Route path="/dashboard/db/group" element={<GroupDatabase />} />
            <Route path="/dashboard/db/personal" element={<PersonalDatabaseEntry />} />
            <Route path="/dashboard/db/personal/vasp" element={<PersonalVaspDatabase />} />
            <Route path="/dashboard/db/personal/qe-epw" element={<PersonalQeEpwDatabase />} />
            <Route path="/dashboard/db/vasp/task/:dbKey/:rowId" element={<VaspTaskDetail />} />
            <Route path="/dashboard/db/qe-epw/task/:dbKey/:rowId" element={<QeEpwTaskDetail />} />
            <Route path="/dashboard/server-monitor" element={<ServerMonitorEntry />} />
            <Route path="/dashboard/server-monitor/users-overview" element={<ServerMonitorUsersOverview />} />
            <Route path="/dashboard/server-monitor/:serverName" element={<ServerMonitorPage />} />
            <Route path="/dashboard/agents" element={<AgentEntry />} />
            <Route path="/dashboard/agents/general-chat" element={<GeneralChatAgent />} />
            <Route path="/dashboard/agents/platform-guide" element={<PlatformGuideAgent />} />
            <Route path="/dashboard/coming-soon" element={<ComingSoon />} />
          </Route>

          <Route path="*" element={<Navigate to="/dashboard" replace />} />
        </Routes>
      </Suspense>
    </BrowserRouter>
  );
}
