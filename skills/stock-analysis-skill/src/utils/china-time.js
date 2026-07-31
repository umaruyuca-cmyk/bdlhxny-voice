export const CHINA_TIME_ZONE = 'Asia/Shanghai';

const EXCHANGE_HOLIDAYS = new Set([
  // 上海证券交易所 2026 年休市安排（周末也列入，便于审计）。
  '2026-01-01', '2026-01-02', '2026-01-03', '2026-01-04',
  '2026-02-14', '2026-02-15', '2026-02-16', '2026-02-17', '2026-02-18',
  '2026-02-19', '2026-02-20', '2026-02-21', '2026-02-22', '2026-02-23',
  '2026-02-28',
  '2026-04-04', '2026-04-05', '2026-04-06',
  '2026-05-01', '2026-05-02', '2026-05-03', '2026-05-04', '2026-05-05',
  '2026-05-09',
  '2026-06-19', '2026-06-20', '2026-06-21',
  '2026-09-20', '2026-09-25', '2026-09-26', '2026-09-27',
  '2026-10-01', '2026-10-02', '2026-10-03', '2026-10-04', '2026-10-05',
  '2026-10-06', '2026-10-07', '2026-10-10',
]);

const COVERED_EXCHANGE_CALENDAR_YEARS = new Set([2026]);

export function getChinaDateTimeParts(date = new Date()) {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: CHINA_TIME_ZONE,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    weekday: 'short',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).formatToParts(date);
  const get = (type) => parts.find((part) => part.type === type)?.value;
  return {
    year: Number(get('year')),
    month: Number(get('month')),
    day: Number(get('day')),
    weekday: get('weekday'),
    hour: Number(get('hour')),
    minute: Number(get('minute')),
    second: Number(get('second')),
  };
}

export function chinaDateString(date = new Date()) {
  const p = getChinaDateTimeParts(date);
  return `${p.year}-${pad(p.month)}-${pad(p.day)}`;
}

export function chinaDateTimeString(date = new Date()) {
  const p = getChinaDateTimeParts(date);
  return `${p.year}-${pad(p.month)}-${pad(p.day)} ${pad(p.hour)}:${pad(p.minute)}:${pad(p.second)}`;
}

export function parseChinaDateTime(dateValue, timeValue = '15:00:00') {
  const date = String(dateValue ?? '').trim();
  const time = String(timeValue ?? '15:00:00').trim();
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date) || !/^\d{2}:\d{2}(?::\d{2})?$/.test(time)) return null;
  const parsed = new Date(`${date}T${time.length === 5 ? `${time}:00` : time}+08:00`);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

export function parseEpochSeconds(value) {
  const number = Number(value);
  if (!Number.isFinite(number) || number < 1_000_000_000) return null;
  const millis = number > 10_000_000_000 ? number : number * 1000;
  const parsed = new Date(millis);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

export function getChinaTradingDayStatus(date = new Date()) {
  const p = getChinaDateTimeParts(date);
  const dateString = `${p.year}-${pad(p.month)}-${pad(p.day)}`;
  const weekend = p.weekday === 'Sat' || p.weekday === 'Sun';
  const holiday = EXCHANGE_HOLIDAYS.has(dateString);
  const calendarCovered = COVERED_EXCHANGE_CALENDAR_YEARS.has(p.year);
  return {
    date: dateString,
    isTradingDay: !weekend && !holiday,
    weekend,
    holiday,
    calendarCovered,
    reason: weekend ? '周末休市' : holiday ? '交易所节假日休市' : calendarCovered ? '交易日历已核验' : '交易日历年份未覆盖',
  };
}

export function countChinaTradingDaysBetween(fromDate, toDate) {
  if (!fromDate || !toDate || fromDate >= toDate) return 0;
  const from = parseChinaDateTime(String(fromDate).slice(0, 10), '12:00:00');
  const to = parseChinaDateTime(String(toDate).slice(0, 10), '12:00:00');
  if (!from || !to || from >= to) return 0;
  let count = 0;
  for (let cursor = new Date(from.getTime() + 86400000); cursor <= to; cursor = new Date(cursor.getTime() + 86400000)) {
    if (getChinaTradingDayStatus(cursor).isTradingDay) count += 1;
  }
  return count;
}

function pad(value) {
  return String(value).padStart(2, '0');
}
