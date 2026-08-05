# routers/devices.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models import Device, Reservation, User
from schemas import DeviceCreate, DeviceOut, ReservationCreate, ReservationOut
from auth import get_current_user
from datetime import datetime

router = APIRouter(prefix="/devices", tags=["devices"])


@router.get("/", response_model=list[DeviceOut])
def list_devices(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    devices = db.query(Device).all()
    return devices


@router.post("/", response_model=DeviceOut)
def create_device(
    device_in: DeviceCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # 简化：允许任何登录用户添加设备；实际可加管理员判断
    if getattr(current_user, "role", None) not in {"admin", "root"}:
        raise HTTPException(status_code=403, detail="only admin or root can create devices")

    device = Device(
        name=device_in.name,
        location=device_in.location,
        description=device_in.description,
    )
    db.add(device)
    db.commit()
    db.refresh(device)
    return device


@router.post("/reserve", response_model=ReservationOut)
def create_reservation(
    res_in: ReservationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    device = db.query(Device).filter(Device.id == res_in.device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="device not found")

    if res_in.start_time >= res_in.end_time:
        raise HTTPException(status_code=400, detail="start_time must be earlier than end_time")

    conflict = db.query(Reservation).filter(
        Reservation.device_id == res_in.device_id,
        Reservation.start_time < res_in.end_time,
        Reservation.end_time > res_in.start_time,
    ).first()
    if conflict:
        raise HTTPException(status_code=409, detail="device is already reserved for the requested time range")

    reservation = Reservation(
        device_id=res_in.device_id,
        user_id=current_user.id,
        start_time=res_in.start_time,
        end_time=res_in.end_time,
        created_at=datetime.utcnow(),
    )
    db.add(reservation)
    db.commit()
    db.refresh(reservation)
    return reservation