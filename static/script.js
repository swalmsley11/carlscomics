const siteHeader = document.querySelector('.site-header');

window.addEventListener('scroll', function () {
  if (window.scrollY > 10) {
    siteHeader.classList.add('scrolled');
  } else {
    siteHeader.classList.remove('scrolled');
  }
});
