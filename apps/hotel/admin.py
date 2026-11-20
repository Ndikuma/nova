from django.contrib import admin
from .models import *
for model in [m for m in locals().values() if isinstance(m,type) and getattr(m,'_meta',None) and m._meta.app_label=='hotel']:
    try: admin.site.register(model)
    except admin.sites.AlreadyRegistered: pass
