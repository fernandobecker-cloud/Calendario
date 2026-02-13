/**
 * CRM Campaign Planner - Frontend Logic
 */

let calendar;

const calendarEl = document.getElementById('calendar');
const loadingEl = document.getElementById('loading');
const errorEl = document.getElementById('error');
const saturationAlertEl = document.getElementById('saturation-alert');
const refreshBtn = document.getElementById('refresh-btn');
const eventModal = document.getElementById('eventModal');
const eventDetails = document.getElementById('eventDetails');
const modalClose = document.querySelector('.modal-close');


/* ================= FETCH API ================= */

async function fetchEvents() {
    try {
        showLoading(true);
        hideError();

        const response = await fetch('/api/events');
        if (!response.ok) throw new Error("Falha ao buscar eventos");

        const events = await response.json();

        showLoading(false);
        return events;

    } catch (error) {
        showLoading(false);
        showError("Erro ao carregar campanhas");
        console.error(error);
        return [];
    }
}


/* ================= CALENDAR ================= */

function initializeCalendar(events) {

    if (!events || events.length === 0) {
        showError("Nenhum evento encontrado");
        return;
    }

    calendar = new FullCalendar.Calendar(calendarEl, {

        initialView: 'dayGridMonth',
        initialDate: new Date(),

        // idioma
        locale: 'pt-br',

        // tradução botões
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

        events: events,

        /* ===== CONTADOR DE CAMPANHAS POR DIA ===== */
        dayCellDidMount: function(info) {

            const dateStr = info.date.toISOString().split('T')[0];

            const count = events.filter(e => e.start === dateStr).length;

            if (count > 0) {

                const badge = document.createElement('div');
                badge.style.fontSize = '11px';
                badge.style.marginTop = '2px';
                badge.style.color = '#666';
                badge.innerText = count + ' campanhas';

                info.el.querySelector('.fc-daygrid-day-top').appendChild(badge);

                // alerta visual se tiver muitas campanhas
                if (count >= 3) {
                    info.el.style.backgroundColor = '#fff3cd';
                }

                if (count >= 5) {
                    info.el.style.backgroundColor = '#f8d7da';
                }
            }
        },

        /* ===== CLIQUE NO EVENTO ===== */
        eventClick: function(info) {

            const e = info.event;
            const p = e.extendedProps;

            eventDetails.innerHTML = `
                <h2>${e.title}</h2>
                <p><b>📅 Data:</b> ${p.data_original}</p>
                <p><b>📣 Canal:</b> ${p.canal}</p>
                <p><b>🛍 Produto:</b> ${p.produto || '—'}</p>
            `;

            eventModal.classList.remove('hidden');
        }
    });

    calendar.render();
    checkSaturation(events);
}


/* ================= SATURAÇÃO ================= */

function checkSaturation(events) {

    const map = {};

    events.forEach(e => {
        map[e.start] = (map[e.start] || 0) + 1;
    });

    const saturated = Object.values(map).some(v => v >= 3);

    if (saturated)
        saturationAlertEl.classList.remove('hidden');
    else
        saturationAlertEl.classList.add('hidden');
}


/* ================= UI ================= */

function showLoading(show){
    loadingEl.classList.toggle('hidden', !show);
}

function showError(msg){
    errorEl.textContent = msg;
    errorEl.classList.remove('hidden');
}

function hideError(){
    errorEl.classList.add('hidden');
}

function closeModal(){
    eventModal.classList.add('hidden');
}

modalClose.addEventListener('click', closeModal);

eventModal.addEventListener('click', e => {
    if(e.target === eventModal) closeModal();
});

refreshBtn.addEventListener('click', async () => {
    calendar.destroy();
    const events = await fetchEvents();
    initializeCalendar(events);
});

/* ================= FILTRO DE CANAL ================= */

function applyChannelFilter(channel){

    let filtered;

    if(channel === 'all'){
        filtered = window.allEvents;
    } else {
        filtered = window.allEvents.filter(e =>
            e.extendedProps.canal.toLowerCase().includes(channel)
        );
    }

    calendar.removeAllEvents();
    calendar.addEventSource(filtered);
}

/* ================= START ================= */

document.addEventListener('DOMContentLoaded', async function() {

    const events = await fetchEvents();

    // guarda globalmente
    window.allEvents = events;

    initializeCalendar(events);

    // ativa clique na legenda
    document.querySelectorAll('.legend-item').forEach(el => {
        el.addEventListener('click', () => {
            const channel = el.dataset.filter;
            applyChannelFilter(channel);
        });
    });

});
