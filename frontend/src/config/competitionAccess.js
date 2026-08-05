const competitionRoles = new Set(['operator', 'viewer']);

export function isCompetitionRole(role) {
  return competitionRoles.has(String(role || '').trim().toLowerCase());
}

export function canWriteCompetitionData(user) {
  return String(user?.role || '').trim().toLowerCase() === 'operator';
}

export function registrationEnabledForEdition(edition = '') {
  return edition !== '107cup';
}

export function passwordResetEnabledForEdition(edition = '') {
  return edition !== '107cup';
}

export function roleLabel(role) {
  const normalized = String(role || '').trim().toLowerCase();
  if (normalized === 'operator') return '操作员';
  if (normalized === 'viewer') return '只读访客';
  return '未授权';
}
