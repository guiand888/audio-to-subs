import "@testing-library/jest-dom"

// jsdom stubs for browser APIs that Radix UI requires but jsdom doesn't implement.
// Without these, click events on Select components produce unhandled TypeErrors.
Element.prototype.hasPointerCapture = () => false
Element.prototype.setPointerCapture = () => {}
Element.prototype.releasePointerCapture = () => {}
// Radix Select calls scrollIntoView on the highlighted item after opening.
Element.prototype.scrollIntoView = () => {}
