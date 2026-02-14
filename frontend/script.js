/**
 * CRM Campaign Planner - Frontend Logic
 */

let calendar;
let selectedChannel = 'all';

const calendarEl = document.getElementById('calendar');
const loadingEl = document.getElementById('loading');
const errorEl = document.getElementById('error');
const saturationAlertEl = document.getElementById('saturation-alert');
const refreshBtn = document.getElementById('refresh-btn');
const eventModal = document.getElementById('eventModal');
const eventDetails = document.getElementById('eventDetails');
const modalClose = document.querySelector('.modal-close');


/* ================= FETCH API ================= */

async function fetchEventsFromApi() {
    const response = await fetch('/api/events');
    if (!response.ok) {
        throw new Error('Falha ao buscar eventos');
    }

    const payload = await response.json();
    return Array.isArray(payload?.events) ? payload.events : [];
}


/* ================= AUXILIARES ================= */

function normalizeChannel(value) {
    return String(value || '').toLowerCase();
}

function applySelectedChannel(events) {
    if (selectedChannel === 'all') return events;
    return events.filter((event) =>
        normalizeChannel(event?.extendedProps?.canal).includes(selectedChannel)
    );
}

function checkSaturation(events) {
    const countByDate = {};

    events.forEach((event) => {
        const date = event?.start;
        if (!date) return;
        countByDate[date] = (countByDate[date] || 0) + 1;
    });

    const saturated = Object.values(countByDate).some((value) => value >= 3);
    saturationAlertEl.classList.toggle('hidden', !saturated);
}

function paintDayCells(events) {
    const countByDate = {};

    events.forEach((event) => {
        const date = event?.start;
        if (!date) return;
        countByDate[date] = (countByDate[date] || 0) + 1;
    });

    document.querySelectorAll('.campaign-count-badge').forEach((el) => el.remove());

    document.querySelectorAll('.fc-daygrid-day').forEach((dayCell) => {
        const date = dayCell.getAttribute('data-date');
        const count = countByDate[date] || 0;

        dayCell.style.backgroundColor = '';
        if (count >= 3) dayCell.style.backgroundColor = '#fff3cd';
        if (count >= 5) dayCell.style.backgroundColor = '#f8d7da';

        if (count <= 0) return;

        const badge = document.createElement('div');
        badge.className = 'campaign-count-badge';
        badge.style.fontSize = '11px';
        badge.style.marginTop = '2px';
        badge.style.color = '#666';
        badge.innerText = `${count} campanhas`;

        const top = dayCell.querySelector('.fc-daygrid-day-top');
        if (top) {
            top.appendChild(badge);
        }
    });
}


/* ================= CALENDAR ================= */

function initializeCalendar() {
    calendar = new FullCalendar.Calendar(calendarEl, {
        initialView: 'dayGridMonth',
        initialDate: new Date(),
        locale: 'pt-br',
        lazyFetching: false,

        buttonText: {
            today: 'Hoje',
            month: 'Mês',
            week: 'Semana',
            day: 'Dia',
            list: 'Lista'
        },

        headerToolbar: {
            left: 'prev,next today',
            center: 'title',
            right: 'dayGridMonth,dayGridWeek'
        },

        height: 'auto',

        events: async function (_fetchInfo, successCallback, failureCallback) {
            try {
                showLoading(true);
                hideError();

                const allEvents = await fetchEventsFromApi();
                window.allEvents = allEvents;

                const filteredEvents = applySelectedChannel(allEvents);
                successCallback(filteredEvents);
            } catch (error) {
                console.error(error);
                showError('Erro ao carregar campanhas');
                failureCallback(error);
            } finally {
                showLoading(false);
            }
        },

        eventClick: function (info) {
            const event = info.event;
            const props = event.extendedProps || {};

            eventDetails.innerHTML = `
                <h2>${event.title}</h2>
                <p><b>📅 Data:</b> ${props.data_original || event.startStr || '—'}</p>
                <p><b>📣 Canal:</b> ${props.canal || '—'}</p>
                <p><b>🛍 Produto:</b> ${props.produto || '—'}</p>
            `;

            eventModal.classList.remove('hidden');
        },

        eventsSet: function (currentEvents) {
            const simpleEvents = currentEvents.map((event) => ({
                start: event.startStr,
            }));

            checkSaturation(simpleEvents);
            paintDayCells(simpleEvents);
        }
    });

    calendar.render();
}


/* ================= UI ================= */

function showLoading(show) {
    loadingEl.classList.toggle('hidden', !show);
}

function showError(msg) {
    errorEl.textContent = msg;
    errorEl.classList.remove('hidden');
}

function hideError() {
    errorEl.classList.add('hidden');
}

function closeModal() {
    eventModal.classList.add('hidden');
}

modalClose.addEventListener('click', closeModal);

eventModal.addEventListener('click', (e) => {
    if (e.target === eventModal) closeModal();
});

refreshBtn.addEventListener('click', () => {
    if (calendar) {
        calendar.refetchEvents();
    }
});


/* ================= FILTRO DE CANAL ================= */

function applyChannelFilter(channel) {
    selectedChannel = channel;
    if (calendar) {
        calendar.refetchEvents();
    }
}


/* ================= START ================= */

document.addEventListener('DOMContentLoaded', function () {
    initializeCalendar();

    document.querySelectorAll('.legend-item').forEach((el) => {
        el.addEventListener('click', () => {
            const channel = el.dataset.filter;
            applyChannelFilter(channel);
        });
    });
});
