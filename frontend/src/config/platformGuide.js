export const platformGuide = {
  name: "低维材料科学实验室综合平台",
  intro:
    "这是一个用于统一管理实验记录、数据库、文献推荐、服务器监控、学术报告、更新日志与反馈建议等科研工作内容的综合平台。",

  modules: [
    {
      key: "notes",
      name: "实验记录本",
      description: "用于记录实验过程、日常进展、任务安排和阶段性结果。",
      entries: [
        {
          name: "记录本",
          path: "/dashboard/notes/journal",
          usage: "记录实验现象、计算过程、想法和每日进展。",
        },
        {
          name: "任务总览",
          path: "/dashboard/notes/tasksentry",
          usage: "查看不同类型任务的总览和分类情况。",
        },
      ],
    },
    {
      key: "db",
      name: "数据库",
      description: "用于查看全组数据库、个人数据库以及任务详情。",
      entries: [
        {
          name: "全组数据库",
          path: "/dashboard/db/group",
          usage: "查看小组共享数据库内容。",
        },
        {
          name: "个人数据库",
          path: "/dashboard/db/personal",
          usage: "进入个人数据库入口，查看 VASP、QE/EPW 等个人任务数据。",
        },
      ],
    },
    {
      key: "server_monitor",
      name: "服务器信息",
      description: "用于查看服务器实时状态、历史使用情况和跨服务器用户分布。",
      entries: [
        {
          name: "服务器入口",
          path: "/dashboard/server-monitor",
          usage: "查看所有服务器概览并进入具体服务器详情。",
        },
        {
          name: "用户使用总览",
          path: "/dashboard/server-monitor/users-overview",
          usage: "查看某个用户当前和历史分别在哪些服务器上使用资源。",
        },
      ],
    },
    {
      key: "papers",
      name: "文献推荐",
      description: "用于查看每日导读、个人订阅和文献库。",
      entries: [
        {
          name: "每日导读",
          path: "/dashboard/papers/daily",
          usage: "查看系统推荐或整理后的每日文献。",
        },
        {
          name: "我的订阅",
          path: "/dashboard/papers/subscription",
          usage: "管理和查看订阅的文献内容。",
        },
        {
          name: "文献库",
          path: "/dashboard/papers/library",
          usage: "浏览和检索已有文献库。",
        },
      ],
    },
    {
      key: "academic_reports",
      name: "学术报告",
      description: "用于查看近期学术报告安排和详细内容。",
      entries: [
        {
          name: "学术报告",
          path: "/dashboard/academic-reports",
          usage: "查看最新报告、报告详情和更多历史报告。",
        },
      ],
    },
    {
      key: "changelog",
      name: "平台更新日志",
      description: "用于查看平台最近更新、修复和新增功能。",
      entries: [
        {
          name: "更新日志",
          path: "/dashboard/changelog",
          usage: "查看平台最近做了哪些改进和修复。",
        },
      ],
    },
    {
      key: "issues",
      name: "反馈与建议",
      description: "用于提交问题、查看反馈和跟踪处理情况。",
      entries: [
        {
          name: "反馈与建议",
          path: "/dashboard/issues",
          usage: "提交问题、建议或查看已有反馈。",
        },
      ],
    },
  ],

  faq: [
    {
      question: "这个网站有什么功能？",
      answer:
        "平台目前主要包含实验记录本、数据库、服务器信息、文献推荐、学术报告、更新日志和反馈建议等功能模块。",
    },
    {
      question: "怎么看服务器使用情况？",
      answer:
        "进入“服务器信息”模块，可以先看服务器入口；如果想看某个用户在哪些服务器上运行任务，可以进入“用户使用总览”。",
      path: "/dashboard/server-monitor",
    },
    {
      question: "怎么查看某个用户在哪些服务器上跑任务？",
      answer:
        "进入“服务器信息”模块中的“用户使用总览”，可以查看实时和历史两个维度的用户跨服务器分布。",
      path: "/dashboard/server-monitor/users-overview",
    },
    {
      question: "怎么查看个人数据库？",
      answer:
        "进入“数据库”模块，再点击“个人数据库”，可以继续进入个人 VASP 或 QE/EPW 数据入口。",
      path: "/dashboard/db/personal",
    },
    {
      question: "怎么找文献？",
      answer:
        "进入“文献推荐”模块，可以选择“每日导读”“我的订阅”或“文献库”。如果只是先看看近期推荐，建议从“每日导读”开始。",
      path: "/dashboard/papers/daily",
    },
    {
      question: "怎么查看学术报告？",
      answer:
        "在首页右侧有学术报告卡片，也可以直接进入“学术报告”页面查看完整列表。",
      path: "/dashboard/academic-reports",
    },
    {
      question: "怎么查看更新日志？",
      answer:
        "进入“平台更新日志”页面，可以查看平台最近做了哪些改进和修复。",
      path: "/dashboard/changelog",
    },
    {
      question: "怎么反馈问题？",
      answer:
        "进入“反馈与建议”页面，可以提交问题、建议，并跟踪处理状态。",
      path: "/dashboard/issues",
    },
    {
      question: "怎么提意见或反馈问题？",
      answer:
        "进入“反馈与建议”页面，可以提交问题、建议，并跟踪处理状态。",
      path: "/dashboard/issues",
    },
  ],

  quickQuestions: [
    "这个网站有什么功能？",
    "怎么看服务器使用情况？",
    "怎么查看某个用户在哪些服务器上跑任务？",
    "怎么查看个人数据库？",
    "怎么找文献？",
    "怎么查看学术报告？",
    "怎么反馈问题？",
  ],
};
