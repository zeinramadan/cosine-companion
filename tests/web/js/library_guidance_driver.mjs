/* Hand the Python static-contract test the value exported by the shipped module. */

import { FIRST_RUN_GUIDANCE } from '../../../src/web/static/js/components/library-guidance.js';

process.stdout.write(JSON.stringify({ firstRunGuidance: FIRST_RUN_GUIDANCE }));
