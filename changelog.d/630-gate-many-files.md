### Fixed

- The merge gate reads a pull request of more than 100 files through GitHub's files API, so one over 300 files no longer fails it with HTTP 406, and one past the API's 3000-file cap stops it naming the gap instead of being judged on a partial list (#630)
