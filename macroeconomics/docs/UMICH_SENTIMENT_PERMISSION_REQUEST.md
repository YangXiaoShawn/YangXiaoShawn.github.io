# University of Michigan sentiment-data permission request

> **Not sent and not authorization.** This is a reviewable request template. The
> repository must keep sentiment ingestion disabled until the University supplies an
> express written response whose scope covers the intended organization and uses below.

The Surveys of Consumers public-data FAQ says publicly displayed material may be used
without permission with citation, but its linked usage agreement also says website data
and materials may not be reproduced, retransmitted, distributed, sold, published, or
broadcast without express written consent. This project therefore applies the more
conservative rule to any stored historical release collection. This is a project safeguard,
not legal advice.

Official references:

- [Usage agreement](https://data.sca.isr.umich.edu/agreement.php)
- [Frequently asked questions](https://data.sca.isr.umich.edu/faq.php)
- [Historical preliminary/final release dates](https://data.sca.isr.umich.edu/technical-docs.php)
- Contact published by the program: `umsurvey@umich.edu`

## Draft request

**Subject:** Permission request for historical Surveys of Consumers release data in a
noncommercial macroeconomic nowcasting research project

Dear Surveys of Consumers team,

I am requesting express written permission for **[LEGAL ORGANIZATION / SCHOOL / EMPLOYER]**
to use historical public Surveys of Consumers materials in a noncommercial research and
portfolio project studying real-time macroeconomic nowcasting and data revisions.

The proposed use is limited to:

1. downloading the public preliminary and final monthly results needed to reconstruct the
   Index of Consumer Sentiment as it was reported at historical release dates;
2. storing source files and extracted index values in an access-controlled local research
   archive; raw files and full extracted histories would not be committed to a public Git
   repository or redistributed;
3. using the historical values as model inputs and publishing only derived forecasts,
   aggregate error metrics, limited attribution tables, and methodological descriptions;
4. citing the data as “University of Michigan, Survey Research Center, Surveys of
   Consumers,” recreating any charts, and making no endorsement claim; and
5. retaining source URLs, release dates, hashes, and retrieval timestamps for reproducible
   audit purposes.

Requested coverage is **January 2002 through the latest available release** (or the widest
period you permit), including both preliminary and final headline Index of Consumer
Sentiment readings when publicly available.

Please confirm whether the activities above are permitted and identify any required license,
subscriber status, citation, display limitation, deletion date, access restriction, or review
of derived outputs. In particular, please clarify whether publishing derived forecasts and
aggregate model metrics is permitted when the underlying extracted time series and source
documents are not redistributed.

Thank you,

**[NAME]**

**[TITLE / PROGRAM]**

**[LEGAL ORGANIZATION]**

**[EMAIL]**

## Evidence required before enabling ingestion

The project gate `require_umich_sentiment_ingestion_approval` requires all of the following:

- current usage agreement reviewed;
- a nonempty reference to the written permission or license;
- confirmation that the named organization and intended uses match the permission scope;
- explicit operator opt-in; and
- a release-by-release coverage/layout audit.

Record the permission date, sender, recipient organization, permitted coverage, permitted
outputs, citation language, restrictions, expiration date, and a secure reference to the
original correspondence. Do not place private correspondence or personal contact details in
the public repository.
