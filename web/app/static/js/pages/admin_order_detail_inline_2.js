document.addEventListener(
    "click",
    function (event) {

        const button =
            event.target.closest(
                "[data-copy]"
            );


        if (!button) {

            return;
        }


        const value =
            button.getAttribute(
                "data-copy"
            );


        if (
            !value
            ||
            !navigator.clipboard
        ) {

            return;
        }


        navigator.clipboard
            .writeText(
                value
            )
            .then(
                function () {

                    const oldText =
                        button.textContent;


                    button.textContent =
                        "已複製";


                    setTimeout(
                        function () {

                            button.textContent =
                                oldText;

                        },
                        1200
                    );

                }
            );

    }
);
