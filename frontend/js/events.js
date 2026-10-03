// External Event Handlers for Z-TRACS UI (CSP-compliant, zero inline scripts)
function initEventBindings() {
  const loginForm = document.getElementById('form-login');
  if (loginForm && !loginForm._bound) {
    loginForm._bound = true;
    loginForm.addEventListener('submit', (e) => {
      if (window.handleLoginForm) window.handleLoginForm(e);
    });
  }

  const registerForm = document.getElementById('form-register');
  if (registerForm && !registerForm._bound) {
    registerForm._bound = true;
    registerForm.addEventListener('submit', (e) => {
      if (window.handleRegisterForm) window.handleRegisterForm(e);
    });
  }

  const linkToRegister = document.getElementById('link-to-register');
  if (linkToRegister && !linkToRegister._bound) {
    linkToRegister._bound = true;
    linkToRegister.addEventListener('click', () => {
      if (window.showRegisterCard) window.showRegisterCard();
    });
  }

  const linkToLogin = document.getElementById('link-to-login');
  if (linkToLogin && !linkToLogin._bound) {
    linkToLogin._bound = true;
    linkToLogin.addEventListener('click', () => {
      if (window.showLoginCard) window.showLoginCard();
    });
  }

  const logoutBtn = document.getElementById('btn-logout');
  if (logoutBtn && !logoutBtn._bound) {
    logoutBtn._bound = true;
    logoutBtn.addEventListener('click', () => {
      if (window.handleLogout) window.handleLogout();
    });
  }

  const refreshUsersBtn = document.getElementById('btn-refresh-users');
  if (refreshUsersBtn && !refreshUsersBtn._bound) {
    refreshUsersBtn._bound = true;
    refreshUsersBtn.addEventListener('click', () => {
      if (window.loadUsersList) window.loadUsersList();
    });
  }
}

if (!window._eventsDelegationBound) {
  window._eventsDelegationBound = true;
  document.addEventListener('click', (e) => {
    const navBtn = e.target.closest('[data-nav]');
    if (navBtn) {
      const targetScreen = navBtn.getAttribute('data-nav');
      if (targetScreen && window.navigateToScreen) {
        window.navigateToScreen(targetScreen);
      }
      return;
    }

    const reportBtn = e.target.closest('[data-download-report]');
    if (reportBtn) {
      const inspId = reportBtn.getAttribute('data-download-report');
      if (inspId && window.downloadReport) {
        window.downloadReport(inspId);
      }
      return;
    }
  });
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initEventBindings);
} else {
  initEventBindings();
}
