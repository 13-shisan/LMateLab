// src/pages/modules/Files.jsx
import { useEffect, useState } from 'react';
import api from '../../api/client';

export default function Files() {
  const [files, setFiles] = useState([]);
  const [fileObj, setFileObj] = useState(null);
  const [uploading, setUploading] = useState(false);

  const loadFiles = async () => {
    const res = await api.get('/files'); // GET /api/files
    setFiles(res.data);
  };

  const onFileChange = (e) => {
    setFileObj(e.target.files[0] || null);
  };

  const upload = async (e) => {
    e.preventDefault();
    if (!fileObj) return;

    const formData = new FormData();
    formData.append('file', fileObj);

    try {
      setUploading(true);
      await api.post('/files/upload', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      setFileObj(null);
      e.target.reset();
      loadFiles();
    } finally {
      setUploading(false);
    }
  };

  useEffect(() => {
    loadFiles();
  }, []);

  return (
    <div className="grid-2">
      {/* 左侧：文件上传 */}
      <div className="card">
        <h3 style={{ marginTop: 0, marginBottom: 16 }}>上传文件</h3>
        <form onSubmit={upload}>
          <div style={{ marginBottom: 12 }}>
            <input type="file" onChange={onFileChange} />
          </div>
          <button className="btn" disabled={uploading}>
            {uploading ? '上传中…' : '上传'}
          </button>
        </form>
        <div style={{ marginTop: 12, fontSize: 12, color: '#6b7280' }}>
          建议上传：数据文件、原始谱图、实验结果文档等。
        </div>
      </div>

      {/* 右侧：文件列表 */}
      <div className="card">
        <h3 style={{ marginTop: 0, marginBottom: 16 }}>文件列表</h3>
        {files.length === 0 && (
          <div style={{ fontSize: 13, color: '#6b7280' }}>暂无文件</div>
        )}
        {files.map((f) => (
          <div key={f.id} className="item-card">
            <div style={{ fontWeight: 600 }}>{f.filename}</div>
            <div className="item-meta">
              {f.uploaded_at && <>上传时间：{f.uploaded_at}</>}
            </div>
            {f.url && (
              <div style={{ marginTop: 4 }}>
                <a
                  href={f.url}
                  target="_blank"
                  rel="noreferrer"
                  style={{ fontSize: 13, color: '#1e64d9' }}
                >
                  下载 / 查看
                </a>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
