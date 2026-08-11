const fullNavigationGroups = [
  {
    key: 'overview',
    label: '',
    items: [
      {
        key: 'dashboard',
        label: '工作台',
        path: '/dashboard',
        icon: 'LayoutDashboard',
        exact: true,
        description: '科研工作与平台状态概览',
      },
    ],
  },
  {
    key: 'research',
    label: '实验与任务',
    items: [
      {
        key: 'journal',
        label: '实验记录本',
        path: '/dashboard/notes/journal',
        icon: 'ClipboardList',
        description: '记录、检索与整理实验内容',
      },
      {
        key: 'tasks',
        label: '计算任务',
        path: '/dashboard/notes/tasksentry',
        icon: 'ListChecks',
        activePrefixes: ['/dashboard/notes/tasks'],
        description: '查看各计算软件任务',
      },
    ],
  },
  {
    key: 'database',
    label: '数据库',
    items: [
      {
        key: 'db-group',
        label: '全组数据库',
        path: '/dashboard/db/group',
        icon: 'Database',
        description: '组内共享数据空间',
      },
      {
        key: 'db-personal',
        label: '个人数据库',
        path: '/dashboard/db/personal',
        icon: 'UserRound',
        exact: true,
        description: '个人数据库入口',
      },
      {
        key: 'db-personal-vasp',
        label: '个人 VASP 数据库',
        path: '/dashboard/db/personal/vasp',
        icon: 'Atom',
        activePrefixes: ['/dashboard/db/vasp/task/'],
        description: 'VASP 计算数据',
      },
      {
        key: 'db-personal-qe-epw',
        label: '个人 QE/EPW 数据库',
        path: '/dashboard/db/personal/qe-epw',
        icon: 'Orbit',
        activePrefixes: ['/dashboard/db/qe-epw/task/'],
        description: 'QE 与 EPW 计算数据',
      },
    ],
  },
  {
    key: 'resources',
    label: '科研资源',
    items: [
      {
        key: 'servers',
        label: '服务器',
        path: '/dashboard/server-monitor',
        icon: 'Server',
        activePrefixes: ['/dashboard/server-monitor/'],
        description: '服务器与任务资源状态',
      },
      {
        key: 'server-users',
        label: '用户资源总览',
        path: '/dashboard/server-monitor/users-overview',
        icon: 'UsersRound',
        exact: true,
        description: '跨服务器用户资源概览',
      },
      {
        key: 'papers-daily',
        label: '每日导读',
        path: '/dashboard/papers/daily',
        icon: 'Newspaper',
        description: '每日文献推荐',
      },
      {
        key: 'papers-subscription',
        label: '我的订阅',
        path: '/dashboard/papers/subscription',
        icon: 'Rss',
        description: '管理文献订阅主题',
      },
      {
        key: 'papers-library',
        label: '文献库',
        path: '/dashboard/papers/library',
        icon: 'Library',
        description: '检索与管理组内文献',
      },
      {
        key: 'academic-reports',
        label: '学术报告',
        path: '/dashboard/academic-reports',
        icon: 'Presentation',
        description: '近期学术报告与活动',
      },
    ],
  },
  {
    key: 'agents',
    label: '智能体',
    items: [
      {
        key: 'agents-entry',
        label: '智能体入口',
        path: '/dashboard/agents',
        icon: 'Bot',
        exact: true,
        description: '选择科研智能体',
      },
      {
        key: 'general-chat',
        label: '通用聊天智能体',
        path: '/dashboard/agents/general-chat',
        icon: 'MessageSquareText',
        description: '通用科研问答',
      },
      {
        key: 'platform-guide',
        label: '平台导览智能体',
        path: '/dashboard/agents/platform-guide',
        icon: 'Map',
        description: '平台功能与流程导览',
      },
    ],
  },
];

const competitionNavigationGroups = Object.freeze([
  Object.freeze({
    key: 'competition',
    label: 'VASP 计算闭环',
    items: Object.freeze([
      Object.freeze({
        key: 'dashboard',
        label: '工作台',
        path: '/dashboard',
        icon: 'LayoutDashboard',
        exact: true,
        description: '竞赛工作流与资源概览',
      }),
      Object.freeze({
        key: 'competition-new',
        label: '新建计算',
        path: '/dashboard/calculations/new',
        icon: 'SquarePlus',
        exact: true,
        description: '配置固定四步 VASP 工作流',
      }),
      Object.freeze({
        key: 'competition-workflows',
        label: '工作流',
        path: '/dashboard/workflows',
        icon: 'Workflow',
        activePrefixes: Object.freeze(['/dashboard/workflows/']),
        description: '查看步骤、作业与失败证据',
      }),
      Object.freeze({
        key: 'competition-results',
        label: '结果',
        path: '/dashboard/results',
        icon: 'ChartNoAxesCombined',
        activePrefixes: Object.freeze(['/dashboard/results/']),
        description: '查看结构、BAND 与 DOS',
      }),
      Object.freeze({
        key: 'competition-vasp-db',
        label: 'VASP 数据库',
        path: '/dashboard/database/vasp',
        icon: 'Database',
        exact: true,
        description: '按元素检索竞赛结果',
      }),
    ]),
  }),
]);

export function navigationGroupsForEdition(edition = '') {
  if (edition === '107cup') return competitionNavigationGroups;
  return fullNavigationGroups;
}

export const activeEdition = import.meta.env?.VITE_LMATELAB_EDITION || '';

export const navigationGroups = navigationGroupsForEdition(activeEdition);

export function dashboardShortcutsForEdition(edition = '') {
  if (edition === '107cup') return [];
  return ['db-personal', 'servers', 'journal', 'general-chat'];
}

export const dashboardShortcuts = dashboardShortcutsForEdition(activeEdition);

function normalizePathname(pathname) {
  if (!pathname || pathname === '/') return '/';
  return pathname.length > 1 ? pathname.replace(/\/+$/, '') : pathname;
}

function flattenNavigation() {
  return navigationGroups.flatMap((group) => group.items);
}

function matchScore(pathname, item) {
  const currentPath = normalizePathname(pathname);
  const itemPath = normalizePathname(item.path);

  if (currentPath === itemPath) return 10000 + itemPath.length;

  const aliasScore = (item.activePrefixes || []).reduce((best, prefix) => {
    return currentPath.startsWith(prefix) ? Math.max(best, 5000 + prefix.length) : best;
  }, -1);
  if (aliasScore >= 0) return aliasScore;

  if (!item.exact && currentPath.startsWith(`${itemPath}/`)) {
    return 1000 + itemPath.length;
  }

  return -1;
}

export function getActiveNavigationItem(pathname) {
  return flattenNavigation().reduce((best, item) => {
    const score = matchScore(pathname, item);
    return score > best.score ? { item, score } : best;
  }, { item: null, score: -1 }).item;
}

export function isNavigationItemActive(pathname, item) {
  return getActiveNavigationItem(pathname)?.key === item.key;
}

export function getNavigationItem(key) {
  return flattenNavigation().find((item) => item.key === key) || null;
}

export function getPageMeta(pathname) {
  const item = getActiveNavigationItem(pathname);
  if (!item) {
    return {
      title: '科研工作台',
      description: '低维材料科学实验室综合平台',
    };
  }

  return {
    title: item.label,
    description: item.description,
  };
}
