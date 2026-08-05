// src/pages/modules/Notes.jsx
import { useEffect, useState } from 'react';
import api from '../../api/client';

export default function Notes() {
  const [notes, setNotes] = useState([]);
  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');

  const loadNotes = async () => {
    const res = await api.get('/notes');
    setNotes(res.data);
  };

  const submit = async (e) => {
    e.preventDefault();
    if (!title.trim() || !content.trim()) return;
    await api.post('/notes', { title, content });
    setTitle('');
    setContent('');
    loadNotes();
  };

  useEffect(() => {
    loadNotes();
  }, []);

  return (
    <div className="grid-2">
      {/* 左侧：新建记录 */}
      <div className="card">
        <h3 style={{ marginTop: 0, marginBottom: 16 }}>新建实验记录</h3>
        <form onSubmit={submit}>
          <div style={{ marginBottom: 10 }}>
            <input
              className="input"
              placeholder="标题，如：2025‑01‑05 电极制备测试"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
            />
          </div>
          <div style={{ marginBottom: 12 }}>
            <textarea
              className="textarea"
              placeholder="记录实验目的、步骤、现象、初步结论等…"
              rows={6}
              value={content}
              onChange={(e) => setContent(e.target.value)}
            />
          </div>
          <button className="btn">保存记录</button>
        </form>
      </div>

      {/* 右侧：最近记录 */}
      <div className="card">
        <h3 style={{ marginTop: 0, marginBottom: 16 }}>最近记录</h3>
        {notes.length === 0 && (
          <div style={{ fontSize: 13, color: '#6b7280' }}>暂无记录</div>
        )}
        {notes.map((n) => (
          <div key={n.id} className="item-card">
            <div style={{ fontWeight: 600 }}>{n.title}</div>
            <div className="item-meta">{n.created_at}</div>
            <p style={{ marginTop: 4, fontSize: 14 }}>{n.content}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
