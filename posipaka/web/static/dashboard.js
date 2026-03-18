// Auto-refresh status indicator
document.body.addEventListener('htmx:afterRequest', function(evt) {
    var status = document.getElementById('status');
    if (evt.detail.successful) {
        status.textContent = 'Connected';
        status.className = 'text-sm text-green-400';
    } else {
        status.textContent = 'Disconnected';
        status.className = 'text-sm text-red-400';
    }
});
