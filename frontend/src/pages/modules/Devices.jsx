// src/pages/modules/Devices.jsx
import { useEffect, useState } from 'react';
import api from '../../api/client';

export default function Devices() {
  const [devices, setDevices] = useState([]);
  const [reservations, setReservations] = useState([]);
  const [selectedDeviceId, setSelectedDeviceId] = useState('');
  const [startTime, setStartTime] = useState('');
  const [endTime, setEndTime] = useState('');
  const [msg, setMsg] = useState('');

  const loadDevices = async () => {
    const res = await api.get('/devices'); // GET /api/devices
    setDevices(res.data);
    if (res.data.length && !selectedDeviceId) {
      setSelectedDeviceId(res.data[0].id);
    }
  };

  const loadReservations = async () => {
    // 按你的后端实际路由改这里
    const res = await api.get('/devices/reservations');
    setReservations(res.data);
  };

  const submitReservation = async (e) => {
    e.preventDefault();
    setMsg('');
    if (!selectedDeviceId || !startTime || !endTime) {
      setMsg('请填写完整预约信息');
      return;
    }

    try {
      await api.post('/devices/reserve', {
        device_id: selectedDeviceId,
        start_time: startTime,
        end_time: endTime,
      });
      setMsg('预约成功');
      setStartTime('');
      setEndTime('');
      loadReservations();
    } catch (err) {
      setMsg(err.response?.data?.detail || '预约失败');
    }
  };

  useEffect(() => {
    loadDevices();
    loadReservations();
  }, []);

  return (
    <div className="grid-2">
      {/* 左列：设备列表 + 预约表单 */}
      <div className="card">
        <h3 style={{ marginTop: 0, marginBottom: 16 }}>新建预约</h3>

        <div style={{ marginBottom: 12 }}>
          <label style={{ fontSize: 13, color: '#4b5563' }}>选择设备</label>
          <select
            className="select"
            value={selectedDeviceId}
            onChange={(e) => setSelectedDeviceId(e.target.value)}
          >
            {devices.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}
              </option>
            ))}
          </select>
        </div>

        <form onSubmit={submitReservation}>
          <div style={{ marginBottom: 10 }}>
            <label style={{ fontSize: 13, color: '#4b5563' }}>开始时间</label>
            <input
              type="datetime-local"
              className="input"
              value={startTime}
              onChange={(e) => setStartTime(e.target.value)}
            />
          </div>
          <div style={{ marginBottom: 10 }}>
            <label style={{ fontSize: 13, color: '#4b5563' }}>结束时间</label>
            <input
              type="datetime-local"
              className="input"
              value={endTime}
              onChange={(e) => setEndTime(e.target.value)}
            />
          </div>

          {msg && (
            <div
              style={{
                marginBottom: 8,
                fontSize: 13,
                color: msg.includes('成功') ? 'green' : 'red',
              }}
            >
              {msg}
            </div>
          )}

          <button className="btn">提交预约</button>
        </form>

        <hr style={{ margin: '20px 0' }} />

        <h4 style={{ marginTop: 0, marginBottom: 10 }}>设备列表</h4>
        {devices.length === 0 && (
          <div style={{ fontSize: 13, color: '#6b7280' }}>暂无设备</div>
        )}
        {devices.map((d) => (
          <div
            key={d.id}
            className="item-card"
            style={{
              cursor: 'pointer',
              borderColor:
                String(d.id) === String(selectedDeviceId)
                  ? 'rgba(30,100,217,0.6)'
                  : undefined,
            }}
            onClick={() => setSelectedDeviceId(d.id)}
          >
            <div style={{ fontWeight: 600 }}>{d.name}</div>
            {d.description && (
              <div style={{ fontSize: 13, color: '#6b7280', marginTop: 2 }}>
                {d.description}
              </div>
            )}
          </div>
        ))}
      </div>

      {/* 右列：预约记录 */}
      <div className="card">
        <h3 style={{ marginTop: 0, marginBottom: 16 }}>预约记录</h3>
        {reservations.length === 0 && (
          <div style={{ fontSize: 13, color: '#6b7280' }}>暂无预约记录</div>
        )}

        {reservations.map((r) => (
          <div key={r.id} className="item-card">
            <div>
              设备：{r.device_name || r.device_id}
            </div>
            <div className="item-meta">
              时间：{r.start_time} ~ {r.end_time}
            </div>
            {r.user_name && (
              <div style={{ fontSize: 12, marginTop: 2 }}>
                使用人：{r.user_name}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
