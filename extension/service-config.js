'use strict';
// Public release configuration. Customers never enter or override this address.
globalThis.CTService = Object.freeze({url:'https://ppsbot.pp.ua/call-translator-saas'});
if (typeof module !== 'undefined') module.exports = globalThis.CTService;
