// src/pages/modules/Projects.jsx
import { useEffect, useState } from 'react';
import api from '../../api/client';

export default function Projects() {
  const [projects, setProjects] = useState([]);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');

  const loadProjects = async () => {
    const res = await api.get('/projects'); // GET /api/projects
    setProjects(res.data);
  };

  const submit = async (e) => {
    e.preventDefault();
    if (!name.trim()) return;
    await api.post('/projects', { name, description });
    setName('');
    setDescription('');
    loadProjects();
  };

  useEffect(() => {
    loadProjects();
  }, []);

  return (
    <div className="grid-2">
      {/* 左侧：新建项目 */}
      <div className="card">
        <h3 style={{ marginTop: 0, marginBottom: 16 }}>新建项目</h3>
        <form onSubmit={submit}>
          <div style={{ marginBottom: 10 }}>
            <input
              className="input"
              placeholder="项目名称，如：钙钛矿太阳能电池效率提升"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </div>
          <div style={{ marginBottom: 12 }}>
            <textarea
              className="textarea"
              placeholder="项目简介（可选）：研究目标、技术路线等"
              rows={4}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>
          <button className="btn">创建项目</button>
        </form>
      </div>

      {/* 右侧：项目列表 */}
      <div className="card">
        <h3 style={{ marginTop: 0, marginBottom: 16 }}>项目列表</h3>
        {projects.length === 0 && (
          <div style={{ fontSize: 13, color: '#6b7280' }}>暂无项目</div>
        )}
        {projects.map((p) => (
          <div key={p.id} className="item-card">
            <div style={{ fontWeight: 600 }}>{p.name}</div>
            <div className="item-meta">
              {p.created_at && <>创建时间：{p.created_at}</>}
            </div>
            {p.description && (
              <p style={{ marginTop: 4, fontSize: 14 }}>{p.description}</p>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
