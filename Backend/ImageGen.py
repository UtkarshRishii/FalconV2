import os
import time
import pollinations
from PIL import Image

def ImageGen(prompt):
    image_model: pollinations.ImageModel = pollinations.image(
        model = "flux-cablyai",
        seed = 0,
        width = 1024,
        height = 1024,
        enhance = False,
        nologo = False,
        private = False,
    )

    image_model.generate(
        prompt = prompt,
        negative = "Anime, cartoony, childish, low quality, blurry, bad anatomy, bad hands, text, watermark",
        save = True,
        file = "Database/Image.png",
    )

def OpenImage():
    timestamp = int(time.time() * 1000)
    image_path = "Database/Image_{timestamp}.png"
    if os.path.exists(image_path):
        image = Image.open(image_path)
        image.show()
    else:
        print("Image file does not exist.")

def Main(newprompt):
    prompt = newprompt
    ImageGen(prompt)
    OpenImage()