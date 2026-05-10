import sys

from collection_tool import run
#https://misskon.com/page/1/?s=%E8%A0%A2%E6%B2%AB%E6%B2%AB
#<div class="entry">
#    <p style="text-align: center;">
#        <a href="https://ouo.io/Lk7adK" target="_blank" class="shortc-button medium green ">
#            <i class="fa fa fa-download"></i>"Download link: MediaFire"
#        </a>
#    </p>
#    <p style="text-align: center;">
#        <a href="https://1024terabox.com/s/1GkFNNSmhVQr9K2wKfn8DkA" target="_blank" class="shortc-button medium blue ">
#            <i class="fa fa fa-download"></i>"Download link: Terabox"
#        </a>
#    </p>
#<div>
if __name__ == "__main__":
    try:
        sys.exit(run())
    except Exception as exc:
        print(f"Application failed to start: {exc}", file=sys.stderr)
        raise
