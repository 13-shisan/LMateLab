// frontend/src/config/modules.js

export const modules = [
  {
    key: 'notes',
    label: '实验记录本',
    children: [
      // ✅ 已在 App.jsx 注册
      { key: 'journal', label: '记录本', icon: '🧪', path: '/dashboard/notes/journal' },

      // ✅ 你 App.jsx 没有这些路由：统一去占位页
      { key: 'template', label: '模板', icon: '📑', path: '/dashboard/coming-soon' },
      { key: 'dataset', label: '数据合集', icon: '📚', path: '/dashboard/coming-soon' },

      // ✅ 已在 App.jsx 注册
      { key: 'tasks-entry', label: '任务总览', icon: '📊', path: '/dashboard/notes/tasksentry' },
      { key: 'tasks-all', label: '全部任务', icon: '📋', path: '/dashboard/notes/tasksall' },
      { key: 'tasks-vasp', label: 'VASP 任务', icon: '⚛️', path: '/dashboard/notes/tasksvasp' },
      { key: 'tasks-qe', label: 'QE 任务', icon: '🧮', path: '/dashboard/notes/tasksqe' },
      { key: 'tasks-gaussian', label: 'Gaussian 任务', icon: '🧪', path: '/dashboard/notes/tasksgaussian' },
      { key: 'tasks-deepmd', label: 'DeepMD 任务', icon: '🤖', path: '/dashboard/notes/tasksdeepmd' },
      { key: 'tasks-lasp', label: 'LASP 任务', icon: '🔬', path: '/dashboard/notes/taskslasp' },
      { key: 'tasks-cp2k', label: 'CP2K 任务', icon: '🧱', path: '/dashboard/notes/taskscp2k' },

      // ✅ 你 App.jsx 没有这个路由：去占位页
      { key: 'tasks-split', label: '按服任务', icon: '🖥️', path: '/dashboard/coming-soon' },
      { key: 'certificate', label: '数字签名证书', icon: '✒️', path: '/dashboard/coming-soon' },
      { key: 'search', label: '检索', icon: '🔍', path: '/dashboard/coming-soon' },
      { key: 'issues', label: '反馈与建议', icon: '📝', path: '/dashboard/issues' },
      { key: 'changelog', label: '日志更新', icon: '📰', path: '/dashboard/changelog' },
    ],
  },

  {
    key: 'db',
    label: '数据库',
    children: [
      // ✅ 已在 App.jsx 注册
      { key: 'db-group', label: '全组数据库', icon: '🗃️', path: '/dashboard/db/group' },
      { key: 'db-personal', label: '个人数据库', icon: '👤', path: '/dashboard/db/personal' },
      { key: 'db-personal-vasp', label: '个人 VASP 数据库', icon: '⚛️', path: '/dashboard/db/personal/vasp' },
      { key: 'db-personal-qe-epw', label: '个人 QE/EPW 数据库', icon: '🧮', path: '/dashboard/db/personal/qe-epw' },
    ],
  },

  {
    key: 'projects',
    label: '项目管理',
    children: [
      // ❌ App.jsx 没有 /projects
      { key: 'project-list', label: '项目列表', icon: '📁', path: '/dashboard/coming-soon' },
    ],
  },

  {
    key: 'files',
    label: '文件收集',
    children: [
      // ❌ App.jsx 没有 /files
      { key: 'file-box', label: '文件夹', icon: '🗂️', path: '/dashboard/coming-soon' },
    ],
  },

  {
    key: 'server_monitor',
    label: '服务器信息',
    children: [
      { key: 'server-monitor-entry', label: '服务器入口', icon: '🖥️', path: '/dashboard/server-monitor' },
      { key: 'server-monitor-users', label: '用户总览', icon: '👥', path: '/dashboard/server-monitor/users-overview' },
    ],
  },

  {
    key: 'papers',
    label: '文献推荐',
    children: [
      // ✅ 关键修复：补上 /dashboard 前缀，严格对齐 App.jsx
      { key: 'daily', label: '每日导读', icon: '👍', path: '/dashboard/papers/daily' },
      { key: 'subscription', label: '我的订阅', icon: '📅', path: '/dashboard/papers/subscription' },
      { key: 'library', label: '文献库', icon: '📒', path: '/dashboard/papers/library' },
      { key: 'academic-reports', label: '学术报告', icon: '📄', path: '/dashboard/academic-reports' },
    ],
  },

  {
    key: 'results',
    label: '我的成果',
    children: [
      // ❌ App.jsx 没有 /results
      { key: 'result', label: '成果', icon: '🏅', path: '/dashboard/coming-soon' },
    ],
  },

  {
    key: 'people',
    label: '研究小组',
    children: [
      // ❌ App.jsx 没有 /people
      { key: 'team', label: '人员', icon: '👥', path: '/dashboard/coming-soon' },
    ],
  },

  {
    key: "agents",
    label: "智能体",
    children: [
      {
        key: "agents-entry",
        label: "智能体入口",
        path: "/dashboard/agents",
      },
      {
        key: "general-chat",
        label: "通用聊天智能体",
        path: "/dashboard/agents/general-chat",
      },
      {
        key: "platform-guide",
        label: "平台导览智能体",
        path: "/dashboard/agents/platform-guide",
      },
    ]
  }
  
];
