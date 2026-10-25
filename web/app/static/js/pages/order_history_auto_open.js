document.addEventListener(
    "DOMContentLoaded",
    function () {

        const params =
            new URLSearchParams(
                window.location.search
            );

        if (
            params.get("open")
            !== "1"
        ) {
            return;
        }

        const button =
            document.querySelector(
                "button.history-dossier-toggle[data-dossier-target]"
            );

        if (!button) {
            return;
        }

        window.setTimeout(
            function () {

                button.click();

                button.scrollIntoView(
                    {
                        block:
                            "center",

                        behavior:
                            "smooth"
                    }
                );

            },
            80
        );
    }
);
